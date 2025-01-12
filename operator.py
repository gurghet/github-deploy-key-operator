import os
import kopf
import kubernetes
import base64
import github
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

# Initialize the Kubernetes API client
kubernetes.config.load_incluster_config()
core_v1_api = kubernetes.client.CoreV1Api()

class GitHubKeyManager:
    def __init__(self, logger):
        self.logger = logger
        self.github_token = self._get_github_token()
        self.github_client = github.Github(self.github_token)

    def _get_github_token(self):
        """Retrieve GitHub token from secret."""
        try:
            secret = core_v1_api.read_namespaced_secret(
                name='ghcr-secret',
                namespace='flux-system'
            )
            token = base64.b64decode(secret.data['github-token']).decode()
            self.logger.info(f"Got GitHub token: {token[:4]}...{token[-4:]}")
            return token
        except kubernetes.client.exceptions.ApiException as e:
            raise kopf.PermanentError(f"Failed to get GitHub token: {e}")

    def get_repository(self, repo_name):
        """Get GitHub repository instance."""
        try:
            repo = self.github_client.get_repo(repo_name)
            self.logger.info(f"Got repository {repo_name}")
            return repo
        except github.GithubException as e:
            raise kopf.PermanentError(f"Failed to get repository: {e}")

    def generate_ssh_key(self):
        """Generate SSH key pair."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )
        
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        )
        
        return private_pem.decode(), public_key.decode()

    def verify_key_exists(self, repo, key_id):
        """Verify GitHub deploy key exists."""
        try:
            repo.get_key(key_id)
            self.logger.info(f"Verified deploy key {key_id} exists in GitHub")
            return True
        except github.GithubException as e:
            self.logger.error(f"Failed to verify deploy key {key_id}: {e}")
            return False

    def delete_key_by_id(self, repo, key_id):
        """Delete a specific GitHub deploy key by ID."""
        try:
            key = repo.get_key(key_id)
            key.delete()
            self.logger.info(f"Successfully deleted deploy key {key_id}")
            return True
        except github.GithubException as e:
            if e.status == 404:
                self.logger.info(f"Deploy key {key_id} was already deleted")
                return True
            self.logger.error(f"Error deleting deploy key {key_id}: {e}")
            return False

    def delete_keys_by_title(self, repo, title):
        """Delete all GitHub deploy keys with a specific title."""
        keys = list(repo.get_keys())
        self.logger.info(f"Found {len(keys)} existing deploy keys")
        
        keys_deleted = 0
        for key in keys:
            if key.title == title:
                self.logger.info(f"Found deploy key with title '{title}' (id: {key.id}), deleting it")
                if self.delete_key_by_id(repo, key.id):
                    keys_deleted += 1
        
        return keys_deleted

class KubernetesSecretManager:
    def __init__(self, logger):
        self.logger = logger

    def create_or_update_secret(self, name, namespace, secret_data, owner_reference):
        """Create or update Kubernetes secret."""
        encoded_data = {k: base64.b64encode(v.encode()).decode() for k, v in secret_data.items()}
        
        try:
            # Try to update existing secret
            secret = core_v1_api.read_namespaced_secret(name=name, namespace=namespace)
            secret.data = encoded_data
            core_v1_api.replace_namespaced_secret(
                name=name,
                namespace=namespace,
                body=secret
            )
            self.logger.info(f"Updated existing secret {name}")
        except kubernetes.client.exceptions.ApiException as e:
            if e.status != 404:
                raise
            
            core_v1_api.create_namespaced_secret(
                namespace=namespace,
                body=kubernetes.client.V1Secret(
                    metadata=kubernetes.client.V1ObjectMeta(
                        name=name,
                        owner_references=[owner_reference]
                    ),
                    type='Opaque',
                    data=encoded_data
                )
            )
            self.logger.info(f"Created new secret {name}")

    def delete_secret_if_exists(self, name, namespace):
        """Delete a Kubernetes secret if it exists."""
        try:
            core_v1_api.delete_namespaced_secret(name=name, namespace=namespace)
            self.logger.info(f"Deleted existing secret {name}")
            return True
        except kubernetes.client.exceptions.ApiException as e:
            if e.status != 404:
                raise
            return False

@kopf.on.create('github.com', 'v1alpha1', 'githubdeploykeys')
def create_deploy_key(spec, logger, patch, **kwargs):
    github_manager = GitHubKeyManager(logger)
    secret_manager = KubernetesSecretManager(logger)
    
    try:
        # Get repository
        repo = github_manager.get_repository(spec['repository'])
        
        # Handle existing keys
        title = spec.get('title', 'Kubernetes-managed deploy key')
        github_manager.delete_keys_by_title(repo, title)
        
        # Generate and create new key
        private_key, public_key = github_manager.generate_ssh_key()
        key = repo.create_key(
            title=title,
            key=public_key,
            read_only=spec.get('readOnly', True)
        )
        logger.info(f"Created new deploy key: {key.id}")
        
        if not github_manager.verify_key_exists(repo, key.id):
            raise kopf.PermanentError("Failed to verify deploy key")
        
        # Update status
        patch['status'] = {'keyId': key.id}
        
        # Create secret
        secret_name = f"{kwargs['meta']['name']}-private-key"
        owner_reference = kubernetes.client.V1OwnerReference(
            api_version=kwargs['body']['apiVersion'],
            kind=kwargs['body']['kind'],
            name=kwargs['body']['metadata']['name'],
            uid=kwargs['body']['metadata']['uid']
        )
        
        secret_manager.delete_secret_if_exists(secret_name, kwargs['meta']['namespace'])
        secret_manager.create_or_update_secret(
            secret_name,
            kwargs['meta']['namespace'],
            {'ssh-privatekey': private_key},
            owner_reference
        )
        
        logger.info(f"Successfully created deploy key {key.id} and secret {secret_name}")
        
    except Exception as e:
        logger.error(f"Error creating deploy key: {str(e)}")
        # Clean up if key was created
        try:
            if 'key' in locals():
                key.delete()
                logger.info(f"Cleaned up deploy key {key.id} after error")
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {str(cleanup_error)}")
        raise kopf.PermanentError(str(e))

@kopf.on.update('github.com', 'v1alpha1', 'githubdeploykeys')
def update_deploy_key(spec, status, logger, patch, old, **kwargs):
    if (old['spec'].get('title', 'Kubernetes-managed deploy key') == spec.get('title', 'Kubernetes-managed deploy key') and
        old['spec'].get('readOnly', True) == spec.get('readOnly', True)):
        logger.info("No relevant changes detected, skipping update")
        return
    
    logger.info("Detected changes in title or readOnly, recreating deploy key")
    create_deploy_key(spec, logger, patch, **kwargs)

@kopf.on.delete('github.com', 'v1alpha1', 'githubdeploykeys')
def delete_deploy_key(spec, meta, status, logger, **kwargs):
    github_manager = GitHubKeyManager(logger)
    
    try:
        repo = github_manager.get_repository(spec['repository'])
        
        # Delete by key ID if available
        key_id = status.get('keyId') if status else None
        if key_id:
            logger.info(f"Found key ID in status: {key_id}")
            if not github_manager.delete_key_by_id(repo, key_id):
                raise kopf.PermanentError(f"Failed to delete deploy key {key_id}")
        else:
            # Delete by title if no key ID
            logger.info("No key ID in status, trying to find key by title")
            title = spec.get('title', 'Kubernetes-managed deploy key')
            keys_deleted = github_manager.delete_keys_by_title(repo, title)
            logger.info(f"Deleted {keys_deleted} deploy key(s) with title '{title}'")
        
    except github.GithubException as e:
        if e.status != 404:  # Ignore if repo not found
            raise kopf.PermanentError(f"Failed to delete deploy key: {e}")
    
    logger.info(f"Secret {meta['name']}-private-key will be deleted by garbage collection")

@kopf.timer('github.com', 'v1alpha1', 'githubdeploykeys', interval=60.0)
def reconcile_deploy_key(spec, status, logger, patch, **kwargs):
    github_manager = GitHubKeyManager(logger)
    
    try:
        repo = github_manager.get_repository(spec['repository'])
        key_id = status.get('keyId') if status else None
        
        if not key_id:
            logger.info("No key ID in status, recreating deploy key")
            create_deploy_key(spec, logger, patch, **kwargs)
            return
        
        try:
            key = repo.get_key(key_id)
            if key.title != spec.get('title', 'Kubernetes-managed deploy key'):
                logger.info(f"Deploy key {key_id} exists but title has changed, recreating")
                create_deploy_key(spec, logger, patch, **kwargs)
            else:
                logger.info(f"Deploy key {key_id} exists and is correctly configured")
        except github.GithubException as e:
            if e.status == 404:
                logger.info(f"Deploy key {key_id} no longer exists, recreating")
                create_deploy_key(spec, logger, patch, **kwargs)
            else:
                logger.error(f"Error checking deploy key {key_id}: {e}")
        
        # Verify secret exists
        secret_name = f"{kwargs['meta']['name']}-private-key"
        try:
            core_v1_api.read_namespaced_secret(
                name=secret_name,
                namespace=kwargs['meta']['namespace']
            )
            logger.info(f"Secret {secret_name} exists")
        except kubernetes.client.exceptions.ApiException as e:
            if e.status == 404:
                logger.info(f"Secret {secret_name} is missing, recreating deploy key")
                create_deploy_key(spec, logger, patch, **kwargs)
            else:
                logger.error(f"Error checking secret {secret_name}: {e}")
                
    except Exception as e:
        logger.error(f"Error during reconciliation: {str(e)}")
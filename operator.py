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
        current_namespace = "operators"  # Set default namespace
        
        try:
            self.logger.info("Running in-cluster, attempting to determine current namespace...")
            try:
                namespace_file = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
                self.logger.debug(f"Reading namespace from {namespace_file}")
                with open(namespace_file, "r") as f:
                    ns = f.read().strip()
                    if ns:  # Only use the namespace if we got a non-empty value
                        current_namespace = ns
                        self.logger.info(f"Successfully determined current namespace: {current_namespace}")
                    else:
                        self.logger.warning("Empty namespace found in service account token, using default 'operators'")
            except (FileNotFoundError, PermissionError) as e:
                self.logger.warning(
                    f"Could not read namespace from service account token ({str(e)}). "
                    "Falling back to default namespace 'operators'"
                )
            
            self.logger.info(f"Attempting to read 'github-token' secret from namespace '{current_namespace}'")
            try:
                secret = core_v1_api.read_namespaced_secret(
                    name='github-token',
                    namespace=current_namespace
                )
            except kubernetes.client.exceptions.ApiException as e:
                if e.status == 404:
                    self.logger.error(
                        f"Secret 'github-token' not found in namespace '{current_namespace}'. "
                        "To fix this:\n"
                        "1. Create a GitHub personal access token\n"
                        "2. Create a Kubernetes secret:\n"
                        "   kubectl create secret generic github-token \\\n"
                        "     --from-literal=GITHUB_TOKEN=your_token_here \\\n"
                        f"     -n {current_namespace}"
                    )
                else:
                    self.logger.error(f"API error while reading secret: {e}")
                raise kopf.PermanentError(f"Failed to get GitHub token: {e}")

            try:
                token = base64.b64decode(secret.data['GITHUB_TOKEN']).decode()
                self.logger.info(f"Successfully retrieved GitHub token (starts with: {token[:4]}...)")
                return token
            except KeyError:
                self.logger.error(
                    "Secret 'github-token' exists but does not contain GITHUB_TOKEN key. "
                    "Please ensure the secret is created with the correct key:\n"
                    "kubectl create secret generic github-token \\\n"
                    "  --from-literal=GITHUB_TOKEN=your_token_here \\\n"
                    f"  -n {current_namespace}"
                )
                raise kopf.PermanentError("Secret exists but GITHUB_TOKEN key is missing")
            except Exception as e:
                self.logger.error(f"Error decoding GitHub token: {e}")
                raise kopf.PermanentError(f"Failed to decode GitHub token: {e}")

        except Exception as e:
            self.logger.error(
                "Unexpected error in _get_github_token. "
                f"Error: {str(e)}\n"
                "For troubleshooting:\n"
                "1. Check pod logs for more details\n"
                "2. Verify RBAC permissions allow reading secrets\n"
                "3. Confirm the github-token secret exists and is properly formatted\n"
                f"4. Verify the operator has access to namespace '{current_namespace}'"
            )
            raise kopf.PermanentError(f"Unexpected error getting GitHub token: {e}")

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

    def create_key(self, repo, title, key, read_only):
        """Create a new GitHub deploy key."""
        try:
            managed_title = f"k8s-operator:{title}"
            return repo.create_key(managed_title, key, read_only)
        except github.GithubException as e:
            self.logger.error(f"Error creating key: {str(e)}")
            raise

    def is_operator_managed_key(self, key_title):
        """Check if a key was created by this operator"""
        return key_title.startswith("k8s-operator:")

    def get_key_base_title(self, key_title):
        """Get the original title without the operator prefix"""
        if self.is_operator_managed_key(key_title):
            return key_title.split(":", 1)[1]
        return key_title

class KubernetesSecretManager:
    def __init__(self, logger):
        self.logger = logger

    def create_or_update_secret(self, name, namespace, private_key, public_key, owner_reference):
        """Create or update Kubernetes secret with SSH keys."""
        # Add github.com to known_hosts
        known_hosts = "github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg="
        
        secret_data = {
            'identity': private_key,
            'identity.pub': public_key,
            'known_hosts': known_hosts
        }
        
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
        
        #Extract readOnly setting
        read_only = spec.get('readOnly', True)
        
        # Handle existing keys
        title = spec.get('title', 'Kubernetes-managed deploy key')
        github_manager.delete_keys_by_title(repo, title)
        
        # Generate and create new key
        private_key, public_key = github_manager.generate_ssh_key()
        key = github_manager.create_key(repo, title, public_key, read_only)
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
            private_key,
            public_key,
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
    """Periodically reconcile the deploy key to ensure it exists."""
    github_manager = GitHubKeyManager(logger)
    
    try:
        repo = github_manager.get_repository(spec['repository'])
        key_id = status.get('keyId') if status else None
        base_title = spec.get('title', 'Kubernetes-managed deploy key')
        managed_title = f"k8s-operator:{base_title}"
        
        # Clean up any operator-managed keys that don't match our key_id
        for key in repo.get_keys():
            if github_manager.is_operator_managed_key(key.title) and (not key_id or key.id != key_id):
                logger.info(f"Found stale operator-managed deploy key {key.id}, deleting")
                github_manager.delete_key_by_id(repo, key.id)
        
        if not key_id:
            logger.info("No key ID in status, recreating deploy key")
            create_deploy_key(spec, logger, patch, **kwargs)
            return
            
        # Check if our key still exists
        try:
            key = repo.get_key(key_id)
            if key.title != managed_title:
                logger.info(f"Deploy key {key_id} exists but title has changed, recreating")
                # Delete old key before creating new one
                github_manager.delete_key_by_id(repo, key_id)
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
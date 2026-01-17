## [1.4.5](https://github.com/gurghet/github-deploy-key-operator/compare/v1.4.4...v1.4.5) (2026-01-17)


### Bug Fixes

* remove stale key cleanup race condition from reconcile ([5f454fb](https://github.com/gurghet/github-deploy-key-operator/commit/5f454fbc82af2bd5cb06e447178f896160d050c1))

## [1.4.4](https://github.com/gurghet/github-deploy-key-operator/compare/v1.4.3...v1.4.4) (2026-01-17)


### Bug Fixes

* use force parameter correctly in create_deploy_key ([c75c3e8](https://github.com/gurghet/github-deploy-key-operator/commit/c75c3e8f9d8855e8db36b2c3e238f9b5dfb4c42c))

## [1.4.3](https://github.com/gurghet/github-deploy-key-operator/compare/v1.4.2...v1.4.3) (2026-01-17)


### Bug Fixes

* skip key creation for existing CRs on operator restart ([48df26c](https://github.com/gurghet/github-deploy-key-operator/commit/48df26c3d6f63c2801fe47d514f24b099fa987d2))

## [1.4.2](https://github.com/gurghet/github-deploy-key-operator/compare/v1.4.1...v1.4.2) (2026-01-17)


### Bug Fixes

* prevent race condition in secret creation ([c12b479](https://github.com/gurghet/github-deploy-key-operator/commit/c12b479544a03dc4f1aaf81af373f72182555b62))

## [1.4.1](https://github.com/gurghet/github-deploy-key-operator/compare/v1.4.0...v1.4.1) (2025-02-23)


### Bug Fixes

* better error handling ([cd4f91b](https://github.com/gurghet/github-deploy-key-operator/commit/cd4f91bf777db03aa2317d2e71e51b8cc390f023))

# [1.4.0](https://github.com/gurghet/github-deploy-key-operator/compare/v1.3.2...v1.4.0) (2025-02-23)


### Features

* any namespace ([6cc337b](https://github.com/gurghet/github-deploy-key-operator/commit/6cc337b9af22d327941d182df94e478654f612ec))

## [1.3.2](https://github.com/gurghet/github-deploy-key-operator/compare/v1.3.1...v1.3.2) (2025-02-16)


### Bug Fixes

* include CRDs in Helm chart OCI package ([1952966](https://github.com/gurghet/github-deploy-key-operator/commit/19529662fc495c37f20d26e7fc7fd11a3209480c))

## [1.3.1](https://github.com/gurghet/github-deploy-key-operator/compare/v1.3.0...v1.3.1) (2025-01-31)


### Bug Fixes

* add semantic-release/exec plugin ([ad17557](https://github.com/gurghet/github-deploy-key-operator/commit/ad175575abad18bd7d7fc0a46beeccb746a790c9))
* add version file output to semantic-release ([c79f276](https://github.com/gurghet/github-deploy-key-operator/commit/c79f276dce47417f56b3e60733497537efa698d9))

# [1.3.0](https://github.com/gurghet/github-deploy-key-operator/compare/v1.2.3...v1.3.0) (2025-01-31)


### Bug Fixes

* add multi-platform docker build ([b3b7380](https://github.com/gurghet/github-deploy-key-operator/commit/b3b7380813ec1e58973154690b65d662c2d73058))
* add Node.js setup for semantic-release ([0b29b05](https://github.com/gurghet/github-deploy-key-operator/commit/0b29b05b3ae87311442dc543db85d94506c185cb))
* install semantic-release dependencies globally ([4e485a6](https://github.com/gurghet/github-deploy-key-operator/commit/4e485a663b40f95feef96927457145f72e25a906))
* remove npm cache option ([000f4f9](https://github.com/gurghet/github-deploy-key-operator/commit/000f4f99686855410f2dda1c3ef8764d98bcb552))


### Features

* add docker image build workflow ([0c0d94e](https://github.com/gurghet/github-deploy-key-operator/commit/0c0d94ede7ce5acc5ba132b1d51e23c34033ee8b))
* add semantic-release and OCI helm chart publishing ([6b13d0a](https://github.com/gurghet/github-deploy-key-operator/commit/6b13d0a70c91a63b1b405e0b09c2b18e814a4300))
* use semantic-release-action for better reliability ([58c6a47](https://github.com/gurghet/github-deploy-key-operator/commit/58c6a47fa7190fa76d39748d0a93855628b58051))

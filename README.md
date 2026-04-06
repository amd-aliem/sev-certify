# SEV OS Certification Framework

A unified framework for testing and certifying operating system support for [AMD Secure Encrypted Virtualization (SEV)](https://www.amd.com/en/developer/sev.html) features on AMD EPYC processors.

## Overview

AMD SEV (Secure Encrypted Virtualization) provides hardware-enabled security features that protect the confidentiality and integrity of virtual machine memory through per-VM encryption keys. This repository enables organizations to:

- **Verify SEV support** on their AMD EPYC servers with automated testing
- **Certify operating systems** for SEV-SNP (Secure Nested Paging) compatibility
- **Access pre-built images** for multiple Linux distributions
- **Track certification status** through an automated GitHub-based workflow

## Features

- 🔐 **Automated SEV-SNP Attestation Testing** - Validates SNP attestation workflows and certificate chains
- 🏗️ **Modular Image Builder** - Built on [mkosi](https://github.com/systemd/mkosi) for reproducible host and guest images
- 🚀 **Self-Service Certification** - Run tests on your own hardware and generate certification reports
- 📊 **Public Certification Matrix** - Track OS/hardware certification status across AMD EPYC generations
- 🔄 **Continuous Integration** - Automated builds and testing through GitHub Actions
- 📦 **Pre-built Images** - Download ready-to-use host and guest images from GitHub Releases

## Supported Distributions

Currently supporting Linux distributions compatible with [`mkosi`](https://github.com/systemd/mkosi):

| Distribution | Versions |
|-------------|----------|
| **Fedora** | 41 |
| **Ubuntu** | 25.04, 25.10 |
| **Debian** | 13 (Trixie), Forky |
| **CentOS** | 10 |
| **Rocky Linux** | 10 |

## Supported Hardware

| AMD EPYC Series | Codename | Native Cert Level | Status |
|-----------------|----------|-------------------|--------|
| **7003** | Milan | 3.0 | ✅ Multiple OSes certified |
| **9004** | Genoa | 3.1 | ⏳ Framework ready |
| **8005** | Sorano | 4.0 | ⏳ Framework ready |
| **9005** | Turin | 4.1 | ⏳ Framework ready |

## Certification Matrix

The following operating systems have been certified for SEV-SNP support on AMD EPYC hardware through this framework. Each certification is validated through automated testing and documented in a GitHub Issue.

### Quick Status Overview

| OS | Status | [EPYC 7003][cert-3.0] | [EPYC 9004][cert-3.1] | [EPYC 8005][cert-4.0] | [EPYC 9005][cert-4.1] |
|---|---|---|---|---|---|
| CentOS 10 | ✅ | [c3.0.0-0](https://github.com/amd-aliem/sev-certify/issues/225) | | | |
| Debian 13 |  ❌ |  [N/A](https://github.com/amd-aliem/sev-certify/issues/152) | | | |
| Debian Forky | ✅ | [c3.0.0-0](https://github.com/amd-aliem/sev-certify/issues/228) | | | |
| Fedora 41 | ✅ | [c3.0.0-0](https://github.com/amd-aliem/sev-certify/issues/229) | | | |
| Rocky 10.1 | ✅ | [c3.0.0-0](https://github.com/amd-aliem/sev-certify/issues/230) | | | |
| Ubuntu 25.04 | ✅ | [c3.0.0-0](https://github.com/amd-aliem/sev-certify/issues/231) | | | |
| Ubuntu 25.10 | ✅ | [c3.0.0-0](https://github.com/amd-aliem/sev-certify/issues/232) | | | |

**Legend:**
- ✅ Certified at latest level for that hardware
- ❌ Not certified at latest level
- ⚠️ Backwards compatibility issues (see [hardware-specific tables][hardware-tables])

See [Certification Level Definitions][cert-definitions] for detailed feature coverage at each level.

## Getting Started

### Prerequisites

To run certification tests, you need:

1. **AMD EPYC Server** with SEV-SNP support (EPYC 7003 or newer)
2. **Dispatch Host** (can be a laptop/workstation) with:
   - GitHub CLI (`gh`) installed and authenticated
   - Network connectivity to the test server
   - Avahi daemon for mDNS support (optional but recommended)

### Quick Start

1. **Download Images**: Get the latest pre-built images from [GitHub Releases](https://github.com/amd-aliem/sev-certify/releases)
   
2. **Prepare Test Server**: Configure your AMD EPYC server for network boot or USB boot

3. **Run Certification**: Follow the detailed guide in [How to Generate Certifications](./docs/how-to-generate-certs.md)

4. **Review Results**: Certification results are automatically posted as GitHub Issues with the `certificate` label

### Self-Service Certification

Organizations can run certification tests on their own SEV-enabled AMD EPYC servers. The automated workflow:

1. Boots the host image on bare-metal hardware
2. Launches embedded guest images with SEV-SNP enabled
3. Executes attestation and feature validation tests
4. Captures logs and generates certification reports
5. Creates a GitHub Issue with results and assigns a certification level

Each certification run produces a GitHub Issue tagged by OS and SEV feature level, making it easy to search and track certifications.

**📚 Detailed Guide**: See [docs/how-to-generate-certs.md](./docs/how-to-generate-certs.md) for step-by-step instructions, including:
- Server hardware setup (HPE, Dell, Lenovo, Supermicro)
- Network configuration (including proxy support)
- GitHub permissions configuration
- Troubleshooting common issues

## Architecture

### Image Build System

Host and guest images are built using [mkosi](https://github.com/systemd/mkosi), a modular OS image builder from the systemd project. The build process:

- **Modular Design**: 20+ reusable modules for common functionality (networking, logging, attestation, etc.)
- **Automated Builds**: GitHub Actions builds images for all supported distributions on every commit
- **Embedded Guests**: Guest images are embedded into host images for self-contained testing
- **EFI Boot**: All images are bootable `.efi` files suitable for UEFI systems

### Key Components

- **Host Image**: Boots on bare-metal EPYC servers, manages test execution
- **Guest Image**: Runs inside QEMU with SEV-SNP enabled, performs attestation tests
- **snpguest**: Tool for SNP attestation report generation and verification
- **snphost**: Host-side SNP utilities and configuration
- **beacon**: Attestation beacon service for validation
- **Logging System**: Captures and uploads guest logs to the host via HTTP

### Certification Workflow

```
┌─────────────────┐
│ Developer       │
│ commits code    │
└────────┬────────┘
         │
         v
┌─────────────────────────┐
│ GitHub Actions          │
│ - Builds images         │
│ - Uploads to Releases   │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│ Organization downloads  │
│ images and boots on     │
│ AMD EPYC server         │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│ Automated tests run     │
│ - SNP attestation       │
│ - Feature validation    │
│ - Log collection        │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│ Results posted to       │
│ GitHub Issue            │
│ - Certification level   │
│ - Test evidence         │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│ Certification matrix    │
│ automatically updated   │
└─────────────────────────┘
```

## Images

Pre-built host and guest images are available in [GitHub Releases](https://github.com/amd-aliem/sev-certify/releases):

- **Development builds** (`devel` tag): Updated on every main branch commit
- **Version releases** (`v*` tags): Stable releases with semantic versioning

Each release includes `.efi` image files for:
- 7 host OS variants (one per supported distribution)
- 7 guest OS variants (one per supported distribution)

Images are constructed through GitHub Workflows and are ready for immediate use on compatible hardware.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines on:

- Code style and conventions
- Pull request requirements
- Testing expectations
- Commit message format (conventional commits)

### Development Workflow

1. Fork the repository and create a feature branch
2. Make changes and test locally (see [how-to-run-guest-manually.md](./docs/how-to-run-guest-manually.md))
3. Ensure commits follow [conventional commit](https://www.conventionalcommits.org/) format
4. Submit a pull request with:
   - Clear description of changes
   - Boot logs or screenshots demonstrating functionality
   - Evidence that tests pass

## Documentation

- [How to Generate Certifications](./docs/how-to-generate-certs.md) - Complete guide for running certification tests
- [How to Run Guest Manually](./docs/how-to-run-guest-manually.md) - Manual testing guide for development
- [Certification Levels](./docs/certifications.md) - Detailed certification definitions and hardware compatibility

## Project Structure

```
sev-certify/
├── .github/workflows/    # CI/CD automation
│   ├── build-and-release.yml          # Image building and release management
│   ├── update-certification-matrix.yml # Automated certification tracking
│   └── lint.yml                        # Commit message linting
├── modules/             # 20+ reusable mkosi modules
│   ├── snpguest/       # SNP attestation testing
│   ├── snphost/        # Host-side SNP utilities
│   ├── logging/        # Log capture and upload (5 sub-modules)
│   ├── guest/          # Base guest configuration
│   ├── host/           # Base host configuration
│   └── ...             # Additional modules
├── images/              # Distribution-specific configurations
│   ├── guest-*/        # Guest image configs (7 distros)
│   └── host-*/         # Host image configs (7 distros)
├── docs/               # Documentation
│   ├── certifications.md
│   ├── how-to-generate-certs.md
│   └── how-to-run-guest-manually.md
└── README.md           # This file
```

## Support

- **Issues**: Report bugs or request features via [GitHub Issues](https://github.com/amd-aliem/sev-certify/issues)
- **Security**: See [SECURITY.md](./SECURITY.md) for security vulnerability reporting
- **Code of Conduct**: See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)

## License

This project is licensed under the terms specified in [LICENSE](./LICENSE).

## Links

[cert-3.0]: ./docs/certifications.md#amd-epyc-7003-milan
[cert-3.1]: ./docs/certifications.md#amd-epyc-9004-genoa
[cert-4.0]: ./docs/certifications.md#amd-epyc-7004-bergamo
[cert-4.1]: ./docs/certifications.md#amd-epyc-9005-bergamo
[hardware-tables]: ./docs/certifications.md#certification-levels-by-hardware
[cert-definitions]: ./docs/certifications.md#certification-level-definitions

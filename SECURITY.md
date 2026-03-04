# Security Policy

## About This Project

Drop Watcher is a personal knife and EDC gear drop monitoring system. It is a read-only 
web monitoring tool — it does not automate purchases, interact with shopping carts, or 
store any user data beyond its own operational logs.

## Supported Versions

This project is under active personal development. Only the latest version on `main` is maintained.

| Version | Supported |
|---------|-----------|
| main    | ✅ Yes    |
| older   | ❌ No     |

## Responsible Disclosure

If you discover a security vulnerability in this project, please report it responsibly:

- **Do not** open a public GitHub issue for security vulnerabilities
- **Do** use GitHub's private vulnerability reporting feature (enabled on this repo)
- **Or** contact me directly via GitHub

I will acknowledge receipt within 48 hours and aim to resolve confirmed vulnerabilities promptly.

## Security Design Principles

This project is built with the following security practices:

- All credentials (API keys, SMTP passwords) are stored in `.env` files which are `.gitignored`
- SSH key-only authentication on the host server — no password auth
- Fail2ban active on SSH and HTTP
- Apache configured to block `.env` and config file access
- Polite, rate-limited polling — no hammering of third party sites
- No user data collected or stored
- No automated purchasing or cart interaction — ever

## What Is NOT In This Repository

The following are never committed to this repository:

- API keys (Anthropic, etc.)
- SMTP credentials
- Server IP addresses or hostnames beyond what is public
- `.env` files of any kind

## Dependency Security

Dependencies are managed via `requirements.txt`. Dependabot alerts are enabled on this 
repository. Known vulnerabilities in dependencies will be addressed promptly.

## Contact

GitHub: [@simonhg321](https://github.com/simonhg321)

HGR

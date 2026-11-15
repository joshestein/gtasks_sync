# Secrets stored via the `security` CLI, not `keyring`

`keyring` writes Keychain items whose ACL trusts the Python interpreter that made them. When uv changes the venv's interpreter path, the launchd agent hits an invisible Keychain prompt and stalls. Storing and reading through `/usr/bin/security` (`add-generic-password -T /usr/bin/security`, `find-generic-password -w`) pins the ACL to a path that never changes. The refresh token and client secret go in one item, written through `security -i` on stdin so they never show in `ps`.

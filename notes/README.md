# Bot Info Notes

Place markdown files here to be served by the info command handlers (`/start`, `/privacy`, `/help`, `/about`, `/contact`, `/changelog`).

## Available files

- `welcome.md` - First information the user sees, served by `/start`
- `privacy.md` - Privacy policy and data handling information
- `help.md` - Help documentation and available commands
- `about.md` - Information about the bot
- `contact.md` - Contact and support information
- `changelog.md` - Version history; only the latest section is sent

## Configuration

The notes directory location can be customized via the `INFO_DIR` environment variable (absolute path).
Default: `<project_root>/notes`

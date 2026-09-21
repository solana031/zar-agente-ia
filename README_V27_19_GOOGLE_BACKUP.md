# ZAR v27.19 — Google Backup

Added persistent, independent Google account backups after successful Google OAuth.

## What is backed up
- Gmail profile and full messages (including message payloads returned by the Gmail API).
- Google Contacts, including names, emails, phones, organizations, photos metadata and other People API fields.
- All calendars visible to the account and their events, including deleted events returned by the API.
- Google Drive file metadata for all non-trashed files accessible to the account.
- Drive file content up to 25 MB by default; Google Docs/Sheets/Slides are exported to PDF/XLSX where supported.

Backups are stored under `ZAR_DATA_DIR/backups/google/<UTC timestamp>/` and a `latest.json` pointer is maintained. The backup runs in a background thread after Google OAuth completes, so the OAuth callback does not wait for a potentially large backup.

## Persistence
Railway should mount its persistent Volume at `/data` (or set `ZAR_DATA_DIR` to the persistent mount). Otherwise local backup files can disappear on redeploy.

## Permissions
`drive.readonly` was added so the backup can read the user's Drive. This requires Google reauthorization once.

## Limits
The default maximum downloaded Drive file size is 25 MB. Override with `ZAR_GOOGLE_BACKUP_MAX_FILE_MB`. Larger files remain recorded in `drive_files.json` but are not downloaded, preventing a single large Drive file from exhausting the Railway Volume.

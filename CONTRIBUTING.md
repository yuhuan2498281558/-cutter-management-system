# Contributing

Thanks for helping improve the Cutter Management System.

## Development workflow

1. Create a focused branch from `master`.
2. Keep changes scoped to one feature or fix and explain domain assumptions in the pull request.
3. Do not add real project drawings, customer data, credentials, database dumps, logs, or generated build output.
4. Run the relevant backend checks and the frontend production build before opening a pull request.

```powershell
cd backend
python manage.py check
python manage.py test application.shield.tests

cd ../web
npm run build
```

For changes to cutter positions or trajectories, document the source mapping and verify every consumer (cutterhead view, tool-change detail, and exports). Keep `ring_no` numeric ordering explicit when querying it.

## Pull requests

Include the user-visible behavior, test commands, migration impact, and any deployment/configuration changes. Screenshots are welcome when a UI or export layout changes, provided they contain only synthetic data.

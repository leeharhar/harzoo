# User data

Harzoo stores **local, machine-specific runtime data** here (`harzoo_user/data/`). Nothing in this folder is meant to be shared or versioned, except this file.

The application creates subdirectories as needed. For example, the browser tool uses:

```text
browser/profile/
```

You can delete contents under this directory when clearing caches or resetting local state. Harzoo will recreate paths on the next run.

Configuration and profiles live under `harzoo_user/config/`, not here.

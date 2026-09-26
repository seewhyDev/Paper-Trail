# Project workflow

- After making changes requested by the user, complete relevant validation, review the diff, then commit and push to `origin` on the current branch. The user has requested automatic Git updates after changes in this project.
- Include only changes belonging to the authorized task. Preserve unrelated user edits and never force-push or rewrite published history.
- Keep API keys, `.env`, private research records, generated run exports, and local-only source media out of Git. Review the staged files for sensitive content before pushing.
- If validation or push fails, report it accurately; do not claim the remote repository was updated.
- This workflow applies to agent-performed work. Do not install background file watchers that commit arbitrary user edits automatically.

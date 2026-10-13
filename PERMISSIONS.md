# StorePro hybrid permissions

Open **Users → Permissions** for an employee. The editor displays the assigned role, three separate panels, effective access, searchable permission categories, and counts. Select a role to preview access; **Save Role** applies it. Grant, Deny, and Remove Override save immediately. Reset clears overrides without changing the assigned role.

Effective permissions are `(role permissions ∪ user grants) − user denials`. Disabled accounts have no effective access. Administrators have no bypass. Even if both override tables contain the same permission, denial wins.

## Upgrade

Close StorePro, extract the update into the existing installation, and run `restart.bat` (or `run.bat` after closing the old server). Startup makes a pre-migration database snapshot and creates the permission tables transactionally. Existing built-in roles receive initial permissions once. Later starts preserve changes, including removed role permissions and explicit denials. No account passwords, inventory, invoices, or historical records are reset.

The SQLite tables use the project's existing snake_case convention: `roles`, `permissions`, `role_permissions`, `user_permission_grants`, `user_permission_denials`. `endpoint_permissions` supports configurable additional requirements on existing actions. Composite primary keys prevent duplicate assignments; foreign keys protect references.

## Policy administration

**Manage Roles & Permissions** requires `users.permissions`. Create roles, edit their permission sets, create permission definitions, and attach additional requirements to existing actions without editing source code. New custom roles start empty. New permissions are not automatically granted to administrators or existing roles.

The catalog includes the requested action vocabulary for each category. An assignment authorizes an implemented operation; it does not create a missing business feature. For example, reserving `products.import` does not add an importer. Additional action requirements are conjunctive: both the built-in permission and every attached permission must be effective. Account, login, and access-administration routes cannot be rebound. Newly implemented routes fail closed until they have a policy.

Built-in access boundaries:

- View permissions open each module. Dashboard and Reports permissions independently authorize their cross-module summaries; they do not require every underlying module's View permission.
- Create, Edit, Delete, Export, Print, and Refund checks protect their corresponding existing operations. Invoice and receipt printing use `sales.print`; export checks use the exported module (profit and loss uses `reports.export`). Browser-native printing cannot be restricted once content is viewable.
- Product price edits require `products.edit` and `products.price_change`. Stock adjustments require `inventory.stock_adjustment`. Receiving purchases requires `purchases.approve`, including receiving during order creation.
- Backup creation, download, restore, and configuration changes require `backups.create`, `backups.export`, `backups.approve`, and `backups.edit` respectively. Editing backup configuration also requires `settings.edit` because it is part of the Settings form. Restore retains password confirmation.
- `users.view` permits viewing employee access; `users.create` and `users.edit` permit account operations within the editor's own effective privileges. `users.permissions` permits policy administration and assigning broader access.
- Search and notifications filter their data sources by effective View permissions. UI visibility is convenience; server enforcement also protects direct requests and AJAX handlers.

Role and override changes are audited. Updates serialize in SQLite and reject stale user versions or role revisions with HTTP 409. Affected user sessions are invalidated; an operator editing their own access keeps the current session with freshly resolved access. At least one active account must retain both `users.permissions` and `backups.approve` so access can be repaired and backups restored. Backups include all permission tables, and restored archives must contain such an operator.

## APIs

- `GET /settings/users/<id>` — permission editor.
- `POST /api/users/<id>/permissions` — JSON `version`, `operation` (`grant`, `deny`, `remove`, `reset`, `role`); include `permission_id` for an override or `role_id` for a role change. Returns authoritative effective access and new version.
- `GET /settings/permissions` — role/catalog/action policy editor.
- `POST /settings/permissions` — JSON `key`, `name`, `category` creates a permission. Key syntax: `category.action` using lowercase letters, digits, and underscores.
- `POST /api/roles` — JSON `name` creates a role.
- `POST /api/roles/<id>/permissions` — JSON `revision`, `permissions` (permission IDs).
- `POST /api/permissions/bindings` — JSON `endpoint`, `method` (`GET` or `POST`), `permission_id`, optional `remove: true`.

All mutations require an authenticated session, effective policy-management permission, and the existing CSRF token in `X-CSRFToken`. Local filesystem access to the database remains outside application authorization; protect the Windows account and backup folders appropriately.

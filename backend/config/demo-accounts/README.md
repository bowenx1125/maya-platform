# Private Demo accounts

The running Demo account catalog is `accounts.private.md`. Copy
`accounts.example.md` to that filename outside Git and replace the example
passwords. The backend reads the Markdown table as a complete desired
identity/membership graph on startup; malformed files fail closed.

Keep the private file readable only by the backend service account:

```sh
chmod 0600 backend/config/demo-accounts/accounts.private.md
```

The catalog is intentionally the only runtime credential source. The older
`backend/config/demo_users.yaml` file is only a one-time migration/rollback
backup for isolated legacy environments and must not be maintained alongside
the private Markdown catalog. If that backup must be used temporarily, set
the server-only `ALLOW_LEGACY_DEMO_USERS=true` switch explicitly and remove it
after migration. Passwords are never returned by the API or written to logs.
`account_key` is an immutable internal key and is not a login field exposed to
browsers; changing a username or removing/re-adding the same key preserves the
platform User UUID.

The surrounding deployment must ignore this directory's private file in both
Git and Docker build context. Do not put real passwords in this example or in
source control.

## Classes

`Maya1001` and `Maya1002` are class teachers: add their accounts to the private
catalog with role `teacher` and an empty group. Set passwords only in that private
file. The existing `Maya` teacher can view every class from Accounts.

The original course and its existing students are Maya1002. The second course
is Maya1001. Startup corrects both labels and scopes each class teacher to the
matching course while preserving course IDs, student memberships and learner work.
In Accounts, teachers can use Add class to
create a named class. It appears in the registration class selector immediately.
Its creator and Maya can manage it; other class teachers gain no access. These
teacher memberships survive catalog synchronization. Class names are unique
after whitespace and case normalization.

Self-registration selects a class, then joins an existing group or creates a new
one inside that class. Group suggestions and counts belong only to the selected
class; the same group name in another class creates a separate group. Students
can change class in Profile; their previous work remains in
its original class and becomes inaccessible. A teacher cannot self-enrol into a
different class. A catalog student's class and explicitly chosen group survive normal startup
synchronization. Students may choose any existing group in their current class.

## Account erasure

Delete physically removes a self-registered student account, credentials,
sessions, memberships, owned public/private Agents, Teams, RAG, Knowledge,
chats and grades. Cached class reports containing the learner's grades are
invalidated; other learners' source records remain. Contributor references on
other people's material become null instead of deleting that material.

The caller must teach every affected class. Self, catalog and teacher accounts
remain protected. Unknown or protected references roll the entire request back;
files unlink only after commit. Supplier cleanup retains its reconciliation
records until voice deletion settles. Migrations never delete existing accounts.

Teachers share one selected class across pages. Switching opens the new class's
module list, clears old detail/group context and caches, and preserves server
membership checks. Public resources are class-bound, not global to a teacher.

Every class has a protected **No Group** group. Active students without a group
in that class join it automatically; teachers stay outside student groups.
`No Group` is reserved case-insensitively: choosing that name joins the
protected group rather than creating another group. Existing custom groups
and their work stay in place.

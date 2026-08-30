# Task Packet

## Goal

What exact outcome must this task deliver?

## Teaching / Product Value

What will a student, teacher or operator understand or do differently?

## Non-goals

What must not change?

## Authority

List the current status, Issue, Gate, ADRs and contracts. Do not point workers at the
archive unless historical evidence is necessary.

## File Ownership

List every owned file/module. State which shared files remain main-window-only.

## Invariants

List permission, immutability, state-machine, privacy, Provider and failure boundaries.

## Acceptance Criteria

List targeted tests, deterministic checks and required human/runtime evidence.

## Provider Budget

Default: `real calls = 0`. If nonzero, freeze provider/model, input data, maximum call
count, maximum cost, timeout, retry, safe errors and stop condition before execution.

## Worker Rules

- work only in the assigned branch/worktree and owned files;
- do not revert, reformat or edit another owner's work;
- do not weaken tests/contracts;
- report changed files, commands and remaining risks;
- do not approve your own Gate.

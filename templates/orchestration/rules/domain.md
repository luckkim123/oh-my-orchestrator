# Domain Rules

<!-- Tailored per project. The other four slots are constant; this one is not. -->

Replace this file with the rules specific to what the project produces. Keep it to
what a vendor worker would get wrong without being told.

Examples of what belongs here:

- **Code project**: the test command and what counts as passing; the build system;
  which directories are generated and must not be hand-edited.
- **Paper project**: never invent a citation; equations in English; the venue's
  formatting rules; which `.bib` entries are verified.
- **Document project**: the deck or report template, the house style spec, the
  verification gate the artifact must pass before it ships.
- **Data/experiment project**: the dataset registry, checksum discipline, what
  constitutes split leakage.

If a project has no rules beyond the other four slots, delete this file rather than
shipping a placeholder. An empty rule reads as "there are no rules here", which is a
different and wrong claim.

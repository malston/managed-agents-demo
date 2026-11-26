# Log triage report rubric

Starter rubric. Tune it to your team's own definition of a good triage report.
The grader scores each criterion on its own, so keep each one checkable.

The deliverable is /mnt/session/outputs/report.md.

1. **File exists.** /mnt/session/outputs/report.md exists and is Markdown.
2. **Sections.** It has these sections, in this order: Summary, Top issues,
   Error spikes, Suggested next steps.
3. **Top issues table.** Top issues is a table with the columns service,
   pattern, count, first seen, last seen, with one row per distinct error or
   warning pattern.
4. **Correct counts.** Every count in the report matches the log exactly.
   Re-count at least the top issue with grep against
   /mnt/session/uploads/app.log.
5. **Root cause named.** For the top issue, the report names a likely root
   cause in one or two sentences, and says it is a hypothesis where the log
   alone can't prove it.
6. **Log lines cited.** Each issue in the table, and each spike, cites at least
   one real log line from the file by timestamp or request ID (req_id).
7. **Severity set.** Each issue has a severity of high, medium or low, and the
   report says in one line what the severity is based on.
8. **Next action given.** Suggested next steps has at least one concrete action
   per high-severity issue, naming the service or team to act.
9. **Length and language.** The report fits on one page (about 400 words or
   fewer, not counting the table) and uses plain, simple language.

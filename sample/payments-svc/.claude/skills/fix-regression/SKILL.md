---
name: fix-regression
description: Fix a production bug with a regression test first. Use when asked to fix a bug found in logs or an incident.
---

1. Find the code that produces the error message from the log. Search for a
   distinctive part of the message, then read the code around it.
2. Write a unit test that shows the bug. Put it in the test file for that
   module. Run the tests and confirm the new test fails for the right reason.
3. Make the smallest code change that fixes the bug. Don't edit settings.
4. Run the whole test suite until every test passes.
5. Write `FIX.md` with: the root cause in one or two sentences, the log line
   that pointed to it, the files you changed, and the test you added.

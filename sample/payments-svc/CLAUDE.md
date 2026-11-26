# payments-svc

Small Python service that charges cards through the stripe-gw gateway.

- Code is in `payments/`, tests are in `tests/`. Standard library only.
- Run the tests with `python -m unittest discover -s tests -t .` from this folder.
- Settings in `payments/settings.py` are owned by the ops team. Don't change them
  to make a bug go away. Fix the code that reads them.
- Every bug fix comes with a regression test that fails before the fix.

CONTINUE:
[x] try to improve readability of deadline colors
[ ] implement another repair
[x] use smarter select operator
[x] add more diverse task lengths to the test example
[x] create more test examples
[x] fix mlflow not logging

[ ] set non-improving stopping and analyze the early results (might not work - iteration counting is broken - on my side)
[ ] try removing some destroy operators from my "advanced planner"

[ ] test the new objective function


# Thoughts
- regret to repair is super for scheduling potentially failing tasks first, also taking into account priority
    [ ] try adding destroy that targets tasks that would make space for the failed-to-fix tasks
- moving farther from deadline does not increase the objective by much
=> quick decline in objective at the beginning, slower afterwards
import pytest

from olostep_link_checker.budget import Budget, BudgetExceeded


def test_n_calls_are_recorded_as_credits_consumed():
    budget = Budget(ceiling=1000)
    for _ in range(17):
        budget.consume()
    assert budget.credits_consumed == 17


def test_consuming_up_to_the_ceiling_succeeds():
    budget = Budget(ceiling=5)
    for _ in range(5):
        budget.consume()
    assert budget.credits_consumed == 5


def test_call_exceeding_ceiling_is_refused_before_being_made():
    budget = Budget(ceiling=5)
    for _ in range(5):
        budget.consume()

    with pytest.raises(BudgetExceeded):
        budget.consume()

    assert budget.credits_consumed == 5  # refused call must not have incremented the counter


def test_unset_ceiling_without_explicit_unlimited_flag_refuses_everything():
    budget = Budget()  # no ceiling, no explicit opt-in
    assert budget.can_consume() is False
    with pytest.raises(BudgetExceeded):
        budget.consume()


def test_unset_ceiling_with_explicit_unlimited_flag_always_allows():
    budget = Budget(unlimited=True)
    assert budget.can_consume() is True
    for _ in range(500):
        budget.consume()
    assert budget.credits_consumed == 500

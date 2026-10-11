from webai.agent import sensitive, sensitive_task


def test_read_only_product_search_with_purchase_prohibition_is_allowed():
    task = (
        "Search for wireless computer mice. Identify three relevant products "
        "and report their names and displayed prices. Use the actual product "
        "listings to verify the information. Do not add anything to the cart "
        "or purchase anything."
    )
    assert not sensitive_task(task)


def test_explicit_purchase_request_is_blocked():
    assert sensitive_task("Find a mouse and purchase it now.")


def test_negated_action_does_not_hide_a_separate_consequential_action():
    assert sensitive_task("Do not purchase anything; send an email to the seller.")


def test_existing_action_level_safety_match_remains_conservative():
    assert sensitive("purchase")
    assert sensitive("send email")

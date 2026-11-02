"""Pure search logic, no search dependencies needed. These retrieval tests run in CI."""

from claimsense.retrieval.evaluate import first_hit_rank, mean_reciprocal_rank, recall_at_k
from claimsense.retrieval.index import fingerprint
from claimsense.retrieval.search import merge_parts, reciprocal_rank_fusion, tokenize


def _chunk(chunk_id, text="some text", searchable=True):
    return {"chunk_id": chunk_id, "text": text, "searchable": searchable}


def test_rrf_hand_worked_example():
    # a = 1/61 + 1/62 = 0.03252, c = 1/63 + 1/61 = 0.03227, b = 1/62 = 0.01613
    assert reciprocal_rank_fusion([["a", "b", "c"], ["c", "a"]]) == ["a", "c", "b"]


def test_rrf_breaks_ties_by_id():
    assert reciprocal_rank_fusion([["b", "a"], ["a", "b"]]) == ["a", "b"]


def test_rrf_keeps_results_when_one_ranking_is_empty():
    assert reciprocal_rank_fusion([["b", "a"], []]) == ["b", "a"]


def test_tokenize_joins_digit_groups():
    assert tokenize("Rs.10,000/- per day") == ["rs", "10000", "per", "day"]


def test_tokenize_splits_the_pdf_hyphen_artefact():
    assert tokenize("pre -existing") == tokenize("pre-existing") == ["pre", "existing"]


def test_tokenize_treats_both_hospitalisation_spellings_alike():
    assert tokenize("Hospitalisation") == tokenize("hospitalization")


def test_merge_parts_removes_the_overlap_only():
    merged = merge_parts(["one two three", "two three four", "four five"])
    assert merged == "one two three four five"


def test_merge_parts_returns_a_single_part_unchanged():
    assert merge_parts(["only part"]) == "only part"


def test_fingerprint_is_stable_across_chunk_order():
    first, second = _chunk("a"), _chunk("b")
    assert fingerprint([first, second], "model") == fingerprint([second, first], "model")


def test_fingerprint_changes_with_text_model_or_search_flag():
    base = fingerprint([_chunk("a")], "model")
    assert fingerprint([_chunk("a", text="edited")], "model") != base
    assert fingerprint([_chunk("a")], "other-model") != base
    assert fingerprint([_chunk("a", searchable=False)], "model") != base


def test_fingerprint_ignores_chunks_that_are_not_searchable():
    base = fingerprint([_chunk("a")], "model")
    assert fingerprint([_chunk("a"), _chunk("b", searchable=False)], "model") == base


def test_first_hit_rank_counts_any_listed_clause():
    assert first_hit_rank(["a", "b"], ["x", "b", "a"]) == 2
    assert first_hit_rank(["a"], ["x", "y"]) is None


def test_recall_counts_only_ranks_within_k():
    assert recall_at_k([1, 5, 6, None], k=5) == 0.5


def test_mean_reciprocal_rank_scores_a_miss_as_zero():
    assert mean_reciprocal_rank([1, 2, None, None]) == 0.375

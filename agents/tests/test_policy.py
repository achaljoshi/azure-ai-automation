from policy import check_diff

OK_NUMSTAT = "10\t2\tassets/js/core.js\n30\t0\ttests/unit/date.test.js\n"


def rules(numstat, diff="", **kw):
    return [v.rule for v in check_diff(numstat, diff, **kw)]


def test_clean_diff_passes():
    assert rules(OK_NUMSTAT, "+const a = 1;\n") == []


def test_protected_and_qa_scope():
    assert rules("1\t1\tpipelines/ci.yml\n") == ["protected-path"]
    assert rules("1\t1\tpackage.json\n") == ["protected-path"]
    assert "qa-write-scope" in rules("5\t0\tsrc/app.js\n", role="qa")
    assert rules("5\t0\ttests/ai-generated/9/a.spec.js\n", role="qa") == []


def test_diff_budget_files_and_lines():
    many = "".join(f"1\t0\tsrc/f{i}.js\n" for i in range(16))
    assert "diff-budget" in rules(many)
    assert "diff-budget" in rules("700\t0\tsrc/big.js\n")
    assert rules("700\t0\tsrc/big.js\n", max_lines=1000) == []


def test_skipped_tests_are_flagged():
    for line in ("+  it.skip('x', () => {})", "+  test.fixme('x')", "+@pytest.mark.skip", "+  xit('x')", "+@Disabled"):
        assert "skipped-test" in rules("3\t0\ttests/a.test.js\n", line)


def test_deleting_tests_counts_as_weakening():
    assert "test-weakened" in rules("0\t40\ttests/unit/date.test.js\n")
    assert rules("0\t40\ttests/unit/date.test.js\n", role="qa", qa_write_dir="tests/") == []  # qa role is judged by write scope instead

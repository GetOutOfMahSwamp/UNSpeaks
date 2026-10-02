from unspeaks.pdf_text import extract_pages, load_pages


def test_one_text_per_page(make_pdf):
    pages = extract_pages(make_pdf(["Resolution 78/1", "Second page"]))
    assert len(pages) == 2
    assert "Resolution 78/1" in pages[0]
    assert "Second page" in pages[1]


def test_line_breaks_are_kept(make_pdf):
    (page,) = extract_pages(make_pdf(["The General Assembly,\nRecalling its resolution 77/1,"]))
    assert page.split("\n") == ["The General Assembly,", "Recalling its resolution 77/1,"]


def test_load_pages_caches_the_text(make_pdf, tmp_path):
    pdf_path = tmp_path / "A_RES_78_1.pdf"
    pdf_path.write_bytes(make_pdf(["Page one", "Page two"]))
    first = load_pages(pdf_path)
    assert (tmp_path / "A_RES_78_1.pages.json").exists()
    assert load_pages(pdf_path) == first == ["Page one", "Page two"]

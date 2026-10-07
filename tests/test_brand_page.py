"""scripts/brand_page.py: the page Streamlit serves first says Northwend."""
import importlib.util
import os
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "brand_page", os.path.join(REPO, "scripts", "brand_page.py"))
brand_page = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brand_page)

STREAMLIT_LIKE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="shortcut icon" href="./favicon.png" />
    <title>Streamlit</title>
  </head>
  <body><div id="root"></div></body>
</html>
"""


class BrandPageTests(unittest.TestCase):

    def test_title_icon_and_description(self):
        html, changes = brand_page.brand_html(STREAMLIT_LIKE)
        self.assertEqual(changes, ["title", "icon", "description"])
        self.assertIn("<title>Northwend</title>", html)
        self.assertNotIn("Streamlit", html)
        self.assertIn('href="./northwend-icon.svg"', html)
        self.assertNotIn("favicon.png", html)
        self.assertIn('<meta name="description"', html)

    def test_running_twice_changes_nothing(self):
        once, _ = brand_page.brand_html(STREAMLIT_LIKE)
        twice, changes = brand_page.brand_html(once)
        self.assertEqual(twice, once)
        self.assertEqual(changes, [])

    def test_a_different_page_is_left_alone(self):
        html, changes = brand_page.brand_html("<html><body>nothing</body></html>")
        self.assertEqual(changes, [])

    def test_brand_writes_the_folder(self):
        folder = tempfile.mkdtemp()
        try:
            with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(STREAMLIT_LIKE)
            self.assertIn("title", brand_page.brand(folder))
            self.assertTrue(os.path.exists(os.path.join(folder, brand_page.ICON_NAME)))
            self.assertEqual(brand_page.brand(folder), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_the_installed_streamlit_page_still_has_what_it_replaces(self):
        # if a Streamlit upgrade changes its index.html, this says so before deploy
        folder = brand_page.static_dir()
        with open(os.path.join(folder, "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        branded, _ = brand_page.brand_html(html)
        self.assertIn("<title>Northwend</title>", branded)
        self.assertIn(brand_page.ICON_NAME, branded)

    def test_render_runs_it_after_installing(self):
        with open(os.path.join(REPO, "render.yaml"), encoding="utf-8") as fh:
            self.assertIn("pip install -r requirements.txt && python scripts/brand_page.py",
                          fh.read())


if __name__ == "__main__":
    unittest.main()

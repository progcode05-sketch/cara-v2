from __future__ import annotations

import json
from pathlib import Path

from app.domain import CarouselPlan, TemplateManifest, TemplatePackage, ensure_parent


class TemplateRepository:
    def __init__(self, builtin_root: Path, import_root: Path) -> None:
        self.builtin_root = builtin_root
        self.import_root = import_root
        self.import_root.mkdir(parents=True, exist_ok=True)

    def _load_from_dir(self, template_dir: Path) -> TemplatePackage:
        manifest = json.loads((template_dir / "template_manifest.json").read_text("utf-8"))
        render_html = (template_dir / "render.html").read_text("utf-8")
        styles_css = ""
        styles_path = template_dir / "styles.css"
        if styles_path.exists():
            styles_css = styles_path.read_text("utf-8")
        head_html = ""
        head_path = template_dir / "head.html"
        if head_path.exists():
            head_html = head_path.read_text("utf-8")
        render_variants: dict[str, str] = {}
        variants_dir = template_dir / "variants"
        if variants_dir.exists():
            for variant_path in sorted(variants_dir.glob("*.html")):
                render_variants[variant_path.stem] = variant_path.read_text("utf-8")
        assets = []
        assets_dir = template_dir / "assets"
        if assets_dir.exists():
            assets = [
                str(path.relative_to(template_dir))
                for path in assets_dir.rglob("*")
                if path.is_file()
            ]
        package = TemplatePackage(
            manifest=TemplateManifest.from_dict(manifest),
            render_html=render_html,
            styles_css=styles_css,
            head_html=head_html,
            render_variants=render_variants,
            assets=assets,
            storage_path=str(template_dir),
        )
        return package

    def list_templates(self) -> list[TemplatePackage]:
        packages: list[TemplatePackage] = []
        seen: set[str] = set()
        for root in (self.builtin_root, self.import_root):
            if not root.exists():
                continue
            for template_dir in sorted(path for path in root.iterdir() if path.is_dir()):
                package = self._load_from_dir(template_dir)
                if package.manifest.id in seen:
                    continue
                packages.append(package)
                seen.add(package.manifest.id)
        return packages

    def get_template(self, template_id: str) -> TemplatePackage:
        for package in self.list_templates():
            if package.manifest.id == template_id:
                return package
        raise KeyError(f"Unknown template_id: {template_id}")

    def save_template(self, package: TemplatePackage) -> TemplatePackage:
        template_dir = self.import_root / package.manifest.id
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / "template_manifest.json").write_text(
            json.dumps(package.manifest.to_dict(), indent=2),
            encoding="utf-8",
        )
        (template_dir / "render.html").write_text(package.render_html, encoding="utf-8")
        if package.styles_css:
            (template_dir / "styles.css").write_text(package.styles_css, encoding="utf-8")
        if package.head_html:
            (template_dir / "head.html").write_text(package.head_html, encoding="utf-8")
        if package.render_variants:
            variants_dir = template_dir / "variants"
            variants_dir.mkdir(parents=True, exist_ok=True)
            for name, html in package.render_variants.items():
                (variants_dir / f"{name}.html").write_text(html, encoding="utf-8")
        package.storage_path = str(template_dir)
        return package


class CarouselRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, carousel_id: str) -> Path:
        return self.root / f"{carousel_id}.json"

    def save(self, carousel: CarouselPlan) -> CarouselPlan:
        path = self._path_for(carousel.id)
        ensure_parent(path)
        path.write_text(json.dumps(carousel.to_dict(), indent=2), encoding="utf-8")
        return carousel

    def get(self, carousel_id: str) -> CarouselPlan:
        path = self._path_for(carousel_id)
        payload = json.loads(path.read_text("utf-8"))
        return CarouselPlan.from_dict(payload)

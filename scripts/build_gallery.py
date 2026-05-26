"""Build the CAD Gallery HTML pages from exported STL files and metadata.

Reads configuration from cad-gallery.yaml, loads metadata from the metadata
directory, and generates HTML pages using Jinja2 templates.
"""

import json
import os
import sys
import glob
import shutil
import subprocess
from datetime import datetime
from email.utils import formatdate

import yaml
from jinja2 import Environment, FileSystemLoader

# Ensure UTF-8 encoding for stdout/stderr
if sys.version_info >= (3, 7):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
else:
    # Fallback for older Python versions
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, errors='replace')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, errors='replace')
    except:
        pass


def safe_print(msg):
    """Print with UTF-8 error handling for environments with encoding issues."""
    try:
        print(msg)
    except (UnicodeEncodeError, UnicodeDecodeError):
        # Fallback: print ASCII representation
        try:
            print(msg.encode('ascii', errors='replace').decode('ascii'))
        except:
            print("[UTF-8 encoding error in message]")


def load_config():
    """Load cad-gallery.yaml configuration."""
    config_path = "cad-gallery.yaml"
    defaults = {
        "freecad_dir": ".",
        "metadata_dir": "metadata",
        "output_dir": "gallery",
        "exports_dir": "exports",
    }

    if not os.path.exists(config_path):
        # Fallback to old name for backwards compatibility
        config_path = "gallery.yaml"

    if not os.path.exists(config_path):
        safe_print("Warning: cad-gallery.yaml not found, using defaults")
        return defaults

    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}

    merged = {**defaults, **cfg}
    if not merged.get("title"):
        merged["title"] = "CAD Gallery"
    return merged


def load_profile():
    """Load maker.yaml if it exists. Returns None if not found (profile is optional)."""
    for path in ("maker.yaml", "profile.yaml"):
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f)
    return None


def load_metadata(metadata_dir, model_name):
    """Load metadata for a model. Returns (metadata_dict, has_metadata)."""
    for ext in (".yaml", ".yml"):
        meta_path = os.path.join(metadata_dir, f"{model_name}{ext}")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                data = yaml.safe_load(f)
            if data:
                return data, True

    return {}, False


def get_git_commit_date(filepath):
    """Get the last git commit date for a file as a Unix timestamp."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", filepath],
            capture_output=True,
            text=True,
            check=True,
        )
        timestamp = result.stdout.strip()
        if timestamp:
            return int(timestamp)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None


def collect_models(config):
    """Collect all models with their metadata and dates."""
    freecad_dir = config["freecad_dir"]
    metadata_dir = config["metadata_dir"]
    exports_dir = config["exports_dir"]

    # Build index of FCStd files with their git commit dates
    fcstd_dates = {}
    pattern = os.path.join(freecad_dir, "*.FCStd")
    for fcstd in glob.glob(pattern):
        name = os.path.splitext(os.path.basename(fcstd))[0]
        git_date = get_git_commit_date(fcstd)
        if git_date:
            mtime = git_date
        else:
            mtime = int(os.path.getmtime(fcstd))

        if name not in fcstd_dates or mtime > fcstd_dates[name]:
            fcstd_dates[name] = mtime

    safe_print(f"Found {len(fcstd_dates)} FCStd files in '{freecad_dir}'")

    # Collect models from exported STL files
    models = []
    for stl in glob.glob(os.path.join(exports_dir, "*.stl")):
        name = os.path.splitext(os.path.basename(stl))[0]

        # Get date
        if name in fcstd_dates:
            mtime = fcstd_dates[name]
        else:
            mtime = int(os.path.getmtime(stl))
            safe_print(f"  Warning: No FCStd found for '{name}', using STL date")

        # Load metadata
        meta, has_metadata = load_metadata(metadata_dir, name)

        # Build metadata file path hint for the fallback message
        metadata_path = os.path.join(metadata_dir, f"{name}.yaml")

        # Check if FCStd file exists for download link
        fcstd_path = os.path.join(freecad_dir, f"{name}.FCStd")
        has_fcstd = os.path.exists(fcstd_path)

        # Check if generated thumbnail exists
        thumbnails_dir = os.path.join(exports_dir, "thumbnails")
        thumbnail_path = os.path.join(thumbnails_dir, f"{name}.png")
        has_thumbnail = os.path.exists(thumbnail_path)

        # Determine primary image
        # Priority: 1) metadata override, 2) first manual image, 3) generated thumbnail
        primary_image = None
        if meta.get("primaryImage"):
            # User explicitly set primaryImage in metadata
            primary_image = meta["primaryImage"]
        elif meta.get("images") and len(meta["images"]) > 0:
            # First manual image from images array
            primary_image = f"images/{name}/{meta['images'][0]['filename']}"
        elif has_thumbnail:
            # Fallback: auto-generated thumbnail
            primary_image = f"thumbnails/{name}.png"

        model = {
            "name": name,
            "stl": f"models/{name}.stl",
            "fcstd": f"freecad/{name}.FCStd" if has_fcstd else None,
            "mtime": mtime,
            "title": meta.get("title", name),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "categories": meta.get("categories", []),
            "images": meta.get("images", []),
            "thumbnail": f"thumbnails/{name}.png" if has_thumbnail else None,
            "primaryImage": primary_image,
            "links": meta.get("links", {}),
            "license": meta.get("license", ""),
            "has_metadata": has_metadata,
            "metadata_path": metadata_path,
        }
        models.append(model)

    # Sort newest first
    models.sort(key=lambda x: x["mtime"], reverse=True)

    safe_print(f"Collected {len(models)} models (sorted by date, newest first)")
    for m in models[:5]:
        status = "with metadata" if m["has_metadata"] else "NO metadata"
        safe_print(f"  {m['name']}: {m['mtime']} ({status})")

    return models


def collect_all_tags(models):
    """Collect all unique tags across all models, sorted alphabetically."""
    tags = set()
    for model in models:
        tags.update(model.get("tags", []))
    return sorted(tags)


def collect_all_categories(models):
    """Collect all unique categories across all models, sorted alphabetically."""
    categories = set()
    for model in models:
        categories.update(model.get("categories", []))
    return sorted(categories)


def copy_assets(config, metadata_dir):
    """Copy STL files, FCStd files and metadata images to the output directory."""
    output_dir = config["output_dir"]
    exports_dir = config["exports_dir"]
    freecad_dir = config["freecad_dir"]

    # Copy STL files
    models_dir = os.path.join(output_dir, "models")
    os.makedirs(models_dir, exist_ok=True)
    for stl in glob.glob(os.path.join(exports_dir, "*.stl")):
        shutil.copy(stl, models_dir)

    # Copy FCStd files
    freecad_dst = os.path.join(output_dir, "freecad")
    os.makedirs(freecad_dst, exist_ok=True)
    for fcstd in glob.glob(os.path.join(freecad_dir, "*.FCStd")):
        shutil.copy(fcstd, freecad_dst)

    # Copy thumbnails
    thumbnails_src = os.path.join(exports_dir, "thumbnails")
    if os.path.isdir(thumbnails_src):
        thumbnails_dst = os.path.join(output_dir, "thumbnails")
        os.makedirs(thumbnails_dst, exist_ok=True)
        for thumb in glob.glob(os.path.join(thumbnails_src, "*.png")):
            shutil.copy(thumb, thumbnails_dst)
        safe_print(f"Copied {len(glob.glob(os.path.join(thumbnails_src, '*.png')))} thumbnails")

    # Copy metadata images
    # Support both: metadata/images/{model_name}/ and metadata/{model_name}/
    images_dst_base = os.path.join(output_dir, "images")
    os.makedirs(images_dst_base, exist_ok=True)
    
    copied_count = 0
    
    # 1. Copy from metadata/images/ if it exists (preferred structure)
    images_src = os.path.join(metadata_dir, "images")
    if os.path.isdir(images_src):
        for model_dir in os.listdir(images_src):
            model_src = os.path.join(images_src, model_dir)
            if os.path.isdir(model_src):
                model_dst = os.path.join(images_dst_base, model_dir)
                if os.path.exists(model_dst):
                    shutil.rmtree(model_dst)
                shutil.copytree(model_src, model_dst)
                copied_count += 1
    
    # 2. Also check metadata/{model_name}/ for images (fallback structure)
    for meta_file in glob.glob(os.path.join(metadata_dir, "*.yaml")) + glob.glob(os.path.join(metadata_dir, "*.yml")):
        model_name = os.path.splitext(os.path.basename(meta_file))[0]
        model_img_src = os.path.join(metadata_dir, model_name)
        
        if os.path.isdir(model_img_src):
            # Check if directory contains image files
            image_files = []
            for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                image_files.extend(glob.glob(os.path.join(model_img_src, f"*{ext}")))
                image_files.extend(glob.glob(os.path.join(model_img_src, f"*{ext.upper()}")))
            
            if image_files:
                model_dst = os.path.join(images_dst_base, model_name)
                os.makedirs(model_dst, exist_ok=True)
                
                for img_file in image_files:
                    shutil.copy(img_file, model_dst)
                
                copied_count += 1
    
    if copied_count > 0:
        safe_print(f"Copied images for {copied_count} model(s) to '{images_dst_base}'")


def find_templates_dir():
    """Find the templates directory.

    Lookup order:
      1. ./scripts/templates  (default location in repo)
      2. $ACTION_PATH/templates  (bundled default templates from the action)
      3. Directory of this script/templates  (local dev / Makefile usage)

    Returns the first existing path, or raises FileNotFoundError.
    """
    candidates = ["scripts/templates"]

    action_path = os.environ.get("ACTION_PATH")
    if action_path:
        candidates.append(os.path.join(action_path, "templates"))

    # Fallback: relative to this script (for local dev / Makefile)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, "templates"))

    for candidate in candidates:
        resolved = os.path.realpath(candidate)
        if os.path.isdir(resolved):
            safe_print(f"Using templates from: {resolved}")
            return resolved

    msg = "No templates directory found. Searched:\n" + "\n".join(f"  - {c}" for c in candidates)
    raise FileNotFoundError(msg)


def build_gallery(config, models, profile):
    """Build the gallery HTML pages using Jinja2 templates."""
    output_dir = config["output_dir"]
    metadata_dir = config["metadata_dir"]

    # Setup Jinja2 — find templates in repo or fall back to action defaults
    templates_dir = find_templates_dir()
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
    )
    env.globals['action_version'] = os.environ.get('ACTION_REF', 'dev')

    # Prepare output directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "view"), exist_ok=True)

    # Copy assets
    copy_assets(config, metadata_dir)
    
    # Copy styles.css from templates to output directory
    styles_src = os.path.join(templates_dir, "styles.css")
    if os.path.exists(styles_src):
        styles_dst = os.path.join(output_dir, "styles.css")
        shutil.copy(styles_src, styles_dst)
        safe_print("Copied styles.css to gallery")

    # Copy user-provided custom CSS if configured
    custom_css_name = None
    custom_css_path = config.get("custom_css")
    if custom_css_path and os.path.exists(custom_css_path):
        custom_css_name = "custom.css"
        custom_dst = os.path.join(output_dir, custom_css_name)
        shutil.copy(custom_css_path, custom_dst)
        safe_print(f"Copied custom CSS from '{custom_css_path}' to gallery")
    elif custom_css_path:
        safe_print(f"Warning: custom_css '{custom_css_path}' not found, skipping")

    # Collect all tags and categories for filter buttons
    all_tags = collect_all_tags(models)
    all_categories = collect_all_categories(models)

    # Build models_json for the JavaScript thumbnail renderer
    models_json = json.dumps(
        [{"name": m["name"], "stl": m["stl"]} for m in models]
    )

    # Get git information for all templates
    git_tag = get_git_tag()
    git_source_url = get_git_source_url()

    # Render index page
    gallery_template = env.get_template("gallery.html")
    index_html = gallery_template.render(
        models=models,
        models_json=models_json,
        profile=profile,
        all_tags=all_tags,
        all_categories=all_categories,
        title=config["title"],
        git_source_url=git_source_url,
        custom_css=custom_css_name,
    )
    index_path = os.path.join(output_dir, "index.html")
    with open(index_path, "w") as f:
        f.write(index_html)

    # Render detail pages
    detail_template = env.get_template("detail.html")
    for i, model in enumerate(models):
        prev_model = models[i - 1] if i > 0 else None
        next_model = models[i + 1] if i < len(models) - 1 else None

        detail_html = detail_template.render(
            model=model,
            prev_model=prev_model,
            next_model=next_model,
            profile=profile,
            title=config["title"],
            git_tag=git_tag,
            git_source_url=git_source_url,
            custom_css=custom_css_name,
        )
        detail_path = os.path.join(output_dir, "view", f"{model['name']}.html")
        with open(detail_path, "w") as f:
            f.write(detail_html)

    # Render about page (only if profile exists)
    if profile:
        about_template = env.get_template("about.html")
        about_html = about_template.render(
            profile=profile,
            title=config["title"],
            git_source_url=git_source_url,
            custom_css=custom_css_name,
        )
        about_path = os.path.join(output_dir, "about.html")
        with open(about_path, "w") as f:
            f.write(about_html)
        safe_print("About page built: about.html")

    safe_print(f"Gallery built: index.html + {len(models)} detail pages in '{output_dir}/'")


def format_rfc822(timestamp):
    """Convert Unix timestamp to RFC 822 date format (for RSS)."""
    return formatdate(timestamp, usegmt=True)


def format_iso8601(timestamp):
    """Convert Unix timestamp to ISO 8601 format (for Atom)."""
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%dT%H:%M:%SZ')


def get_base_url():
    """Derive base URL from git remote or environment variable.
    
    Priority:
      1. GALLERY_BASE_URL env var (user-provided)
      2. Extract from git remote (github.com/user/repo -> https://user.github.io/repo)
      3. Fallback to localhost
    """
    base_url = os.environ.get('GALLERY_BASE_URL')
    if base_url:
        return base_url.rstrip('/')
    
    try:
        result = subprocess.run(
            ['git', 'config', '--get', 'remote.master.url'],
            capture_output=True, text=True, check=True
        )
        remote = result.stdout.strip()
        
        # Parse: git@github.com:user/repo.git or https://github.com/user/repo
        if 'github.com' in remote:
            # Extract user and repo from various git URL formats
            parts = remote.replace(':', '/').replace('.git', '').split('/')
            user = parts[-2]
            repo = parts[-1]
            return f'https://{user}.github.io/{repo}'
    except:
        # Try origin as fallback
        try:
            result = subprocess.run(
                ['git', 'config', '--get', 'remote.origin.url'],
                capture_output=True, text=True, check=True
            )
            remote = result.stdout.strip()
            if 'github.com' in remote:
                parts = remote.replace(':', '/').replace('.git', '').split('/')
                user = parts[-2]
                repo = parts[-1]
                return f'https://{user}.github.io/{repo}'
        except:
            pass
    
    return 'http://localhost:8000'  # Fallback


AGGREGATOR_URL = "https://webhook.site/9bcff9a7-e5a5-42ab-835c-ad2fc18d9151"


def get_git_source_url():
    """Derive the HTTPS source URL from the git remote.

    Handles both SSH (git@host:user/repo.git) and HTTPS remotes.
    Returns None if the remote cannot be determined.
    """
    try:
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            capture_output=True, text=True, check=True
        )
        remote = result.stdout.strip()
        if not remote:
            return None

        # SSH: git@host:user/repo.git  →  https://host/user/repo
        if remote.startswith('git@'):
            # git@github.com:user/repo.git
            remote = remote[len('git@'):]          # github.com:user/repo.git
            remote = remote.replace(':', '/', 1)   # github.com/user/repo.git
            remote = remote.rstrip('/')
            if remote.endswith('.git'):
                remote = remote[:-4]
            return f'https://{remote}'

        # HTTPS: https://host/user/repo.git  →  https://host/user/repo
        if remote.startswith('http://') or remote.startswith('https://'):
            remote = remote.rstrip('/')
            if remote.endswith('.git'):
                remote = remote[:-4]
            return remote

        return None
    except Exception:
        return None


def get_git_tag():
    """Get the current git tag (latest annotated tag).
    
    Returns the tag name (e.g., 'v2.2.6') or 'main' as fallback.
    """
    try:
        result = subprocess.run(
            ['git', 'describe', '--tags', '--abbrev=0'],
            capture_output=True, text=True, check=True
        )
        tag = result.stdout.strip()
        if tag:
            return tag
    except Exception:
        pass
    return 'main'


def build_discovery(config, models, profile, base_url):
    """Generate gallery/discovery/cad-gallery.json discovery document."""
    output_dir = config["output_dir"]
    discovery_dir = os.path.join(output_dir, 'discovery')
    os.makedirs(discovery_dir, exist_ok=True)

    generator_version = os.environ.get('ACTION_REF', 'dev')
    git_source_url = get_git_source_url()
    now_iso = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    discovery = {
        "version": "1",
        "generator": "freecad-action",
        "generator_version": generator_version,
        "git_source_url": git_source_url,
        "profile": profile if profile else None,
        "gallery": {
            "url": base_url,
            "feed_rss": f"{base_url}/rss.xml",
            "feed_atom": f"{base_url}/atom.xml",
            "model_count": len(models),
            "last_updated": now_iso,
        },
        "models": [
            {
                "name": m["name"],
                "title": m.get("title") or m["name"],
                "url": f"{base_url}/view/{m['name']}.html",
                "stl_url": f"{base_url}/{m['stl']}",
                "fcstd_url": f"{base_url}/{m['fcstd']}" if m.get("fcstd") else None,
                "tags": m.get("tags") or [],
                "categories": m.get("categories") or [],
                "license": m.get("license") or None,
                "updated_at": datetime.utcfromtimestamp(m["mtime"]).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "thumbnail_url": f"{base_url}/{m['thumbnail']}" if m.get("thumbnail") else None,
                "primary_image_url": f"{base_url}/{m['primaryImage']}" if m.get("primaryImage") else None,
                "images": [
                    {
                        "url": f"{base_url}/images/{m['name']}/{img['filename']}",
                        "caption": img.get("caption")
                    }
                    for img in m.get("images", [])
                ],
                "links": m.get("links") or {},
            }
            for m in models
        ],
    }

    discovery_path = os.path.join(discovery_dir, 'cad-gallery.json')
    with open(discovery_path, 'w') as f:
        json.dump(discovery, f, indent=2)

    safe_print(f"Discovery document built: discovery/cad-gallery.json ({len(models)} models)")


def ping_aggregator(base_url):
    """Send a POST ping to the aggregator URL."""
    import urllib.request
    import urllib.error

    discovery_url = f"{base_url}/discovery/cad-gallery.json"
    git_source_url = get_git_source_url()

    payload = json.dumps({
        "discovery_url": discovery_url,
        "git_source_url": git_source_url,
        "event": "push",
    }).encode('utf-8')

    req = urllib.request.Request(
        AGGREGATOR_URL,
        data=payload,
        headers={'Content-Type': 'application/json', 'User-Agent': 'freecad-action'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            safe_print(f"Aggregator ping sent to {AGGREGATOR_URL} (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        safe_print(f"Aggregator ping failed: HTTP {e.code} {e.reason}")
    except Exception as e:
        safe_print(f"Aggregator ping failed: {e}")


def build_feeds(config, models, profile):
    """Build RSS and Atom feeds."""
    output_dir = config["output_dir"]
    templates_dir = find_templates_dir()
    
    env = Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
    )
    
    # Custom filters for date formatting
    env.filters['format_rfc822'] = format_rfc822
    env.filters['format_iso8601'] = format_iso8601
    
    base_url = get_base_url()
    
    # Render RSS feed
    rss_template = env.get_template('rss.xml')
    rss_content = rss_template.render(
        models=models,
        profile=profile,
        base_url=base_url,
    )
    rss_path = os.path.join(output_dir, 'rss.xml')
    with open(rss_path, 'w') as f:
        f.write(rss_content)
    
    # Render Atom feed
    atom_template = env.get_template('atom.xml')
    atom_content = atom_template.render(
        models=models,
        profile=profile,
        base_url=base_url,
        now=int(datetime.now().timestamp()),
    )
    atom_path = os.path.join(output_dir, 'atom.xml')
    with open(atom_path, 'w') as f:
        f.write(atom_content)
    
    safe_print(f"Feeds built: rss.xml + atom.xml ({len(models)} models, base URL: {base_url})")


def main():
    config = load_config()
    profile = load_profile()
    models = collect_models(config)

    if not models:
        safe_print("No models found. Make sure STL exports exist.")
        return

    base_url = get_base_url()
    build_gallery(config, models, profile)
    build_feeds(config, models, profile)
    build_discovery(config, models, profile, base_url)

    if os.environ.get('SEND_PING', '').lower() == 'true':
        ping_aggregator(base_url)


if __name__ == "__main__":
    main()

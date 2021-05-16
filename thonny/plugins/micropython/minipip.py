import io
import json
import os.path
import shutil
import subprocess
import tarfile
from typing import Union, List, Dict, Any, Optional
from urllib.error import HTTPError
from urllib.request import urlopen
import pkg_resources
import logging

from pkg_resources import Requirement

logger = logging.getLogger(__name__)

MP_ORG_INDEX = "https://micropython.org/pi"
DEFAULT_INDEX_URLS = [MP_ORG_INDEX, "https://pypi.org/pypi"]


class UserError(RuntimeError):
    pass


class NotUpipCompatible(RuntimeError):
    pass


class DistributionNotFoundError(RuntimeError):
    pass


def install(
    spec: Union[List[str], str], install_dir: str = None, index_urls: List[str] = None
) -> None:
    if isinstance(spec, str):
        specs = [spec]
    else:
        specs = spec

    if not install_dir:
        install_dir = os.getcwd()

    if not index_urls:
        index_urls = DEFAULT_INDEX_URLS

    try:
        pip_specs = _install_all_upip_compatible(specs, install_dir, index_urls)

        if pip_specs:
            _install_with_pip(pip_specs, install_dir, index_urls)
    except UserError as e:
        print("ERROR:", e, file=sys.stderr)
        exit(1)
    except subprocess.CalledProcessError:
        # assuming pip already printed the error
        exit(1)


def _install_all_upip_compatible(
    specs: List[str], install_dir: str, index_urls: List[str]
) -> List[str]:
    """Returns list of specs which must be installed with pip"""
    installed_specs = set()
    specs_to_be_processed = specs.copy()
    pip_specs = []

    while specs_to_be_processed:
        spec = specs_to_be_processed.pop(0)
        if spec in installed_specs or spec in pip_specs:
            continue

        req = pkg_resources.Requirement.parse(spec)

        logger.info("Processing '%s'", req)
        meta = _fetch_metadata(req, index_urls)
        version = meta["info"]["version"]
        logger.info("Inspecting version %s", version)
        assets = meta["releases"][version]

        if len(assets) != 1 or not assets[0]["url"].endswith(".tar.gz"):
            logger.info(
                "'%s' will be installed with pip (not having single tar.gz asset).",
                req.project_name,
            )
            pip_specs.append(spec)
            continue

        try:
            dep_specs = _install_single_upip_compatible_from_url(
                req.project_name, assets[0]["url"], install_dir
            )
            installed_specs.add(spec)
            if dep_specs:
                logger.info("Dependencies of '%s': %s", spec, dep_specs)
                for dep_spec in dep_specs:
                    if dep_spec not in installed_specs and dep_spec not in specs_to_be_processed:
                        specs_to_be_processed.append(dep_spec)
        except NotUpipCompatible:
            pip_specs.append(spec)

    return pip_specs


def _install_single_upip_compatible_from_url(
    project_name: str, url: str, target_dir: str
) -> List[str]:
    with urlopen(url) as fp:
        download_data = fp.read()

    tar = tarfile.open(fileobj=io.BytesIO(download_data), mode="r:gz")

    deps = []

    content: Dict[str, Optional[bytes]] = {}

    for info in tar:
        if "/" in info.name:
            dist_name, rel_name = info.name.split("/", maxsplit=1)
        else:
            dist_name, rel_name = info.name, ""

        if rel_name == "setup.py":
            logger.debug("The archive contains setup.py. The package will be installed with pip")
            raise NotUpipCompatible()

        if ".egg-info/PKG-INFO" in rel_name:
            continue

        if ".egg-info/requires.txt" in rel_name:
            for line in tar.extractfile(info):
                line = line.strip()
                if line and not line.startswith(b"#"):
                    deps.append(line.decode())
            continue

        if ".egg-info" in rel_name:
            continue

        if info.isdir():
            content[os.path.join(target_dir, rel_name)] = None
        elif info.isfile():
            content[os.path.join(target_dir, rel_name)] = tar.extractfile(info).read()

    # write files only after the package is fully inspected and found to be upip compatible
    logger.info("Extracting '%s' from %s to %s", project_name, url, os.path.abspath(target_dir))
    for path in content:
        data = content[path]
        if data is None:
            os.makedirs(path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fp:
                fp.write(data)

    return deps


def _install_with_pip(specs: List[str], target_dir: str, index_urls: List[str]):
    logger.info("Installing with pip: %s", specs)

    suitable_indexes = [url for url in index_urls if url != MP_ORG_INDEX]
    if not suitable_indexes:
        raise UserError("No suitable indexes for pip")

    args = [
        "--no-input",
        "--no-color",
        "--disable-pip-version-check",
        "install",
        "--upgrade",
        "--target",
        target_dir,
    ]

    args += ["--index-url", suitable_indexes.pop(0)]
    while suitable_indexes:
        args += ["--extra-index-url", suitable_indexes.pop(0)]

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
        ]
        + args
        + specs
    )

    for name in os.listdir(target_dir):
        if name.endswith(".dist-info"):
            shutil.rmtree(os.path.join(target_dir, name))


def _fetch_metadata(req: Requirement, index_urls: List[str]) -> Dict[str, Any]:

    ver_specs = req.specs

    for i, index_url in enumerate(index_urls):
        try:
            url = "%s/%s/json" % (index_url, req.project_name)
            logger.info("Querying package metadata from %s", url)
            with urlopen(url) as fp:
                main_meta = json.load(fp)
            current_version = main_meta["info"]["version"]

            if not ver_specs:
                ver_specs = ["==" + current_version]

            ver = _resolve_version(req, main_meta)
            if ver is None:
                logger.info("Could not find suitable version from %s", index_url)
                continue

            if ver == current_version:
                # micropython.org only has main meta
                return main_meta
            else:
                url = "%s/%s/%s/json" % (index_url, req.project_name, ver)
                logger.debug("Querying version metadata from %s", url)
                with urlopen(url) as fp:
                    logger.info("Found '%s' from %s", req, index_url)
                    return json.load(fp)
        except HTTPError as e:
            if e.code == 404:
                logger.info("Could not find '%s' from %s", req.project_name, index_url)
            else:
                raise

    raise UserError(
        "Could not find '%s' from any of the indexes %s" % (req.project_name, index_urls)
    )


def _read_requirements(req_file: str) -> List[str]:
    if not os.path.isfile(req_file):
        raise UserError("Can't find '%s'" % req_file)

    result = []
    with open(req_file, "r", errors="replace") as fp:
        for line in fp:
            line = line.strip()
            if line and not line.startswith("#"):
                result.append(line)

    return result


def _resolve_version(req: Requirement, main_meta: Dict[str, Any]) -> Optional[str]:
    matching_versions = []
    for ver in main_meta["releases"]:
        if ver in req and len(main_meta["releases"][ver]) > 0:
            matching_versions.append(ver)

    if not matching_versions:
        return None

    return sorted(matching_versions, key=pkg_resources.parse_version)[-1]


def main(raw_args):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", help="Currently the only supported command is 'install'", choices=["install"]
    )
    parser.add_argument(
        "specs",
        help="Package specification, eg. 'micropython-os' or 'micropython-os>=0.6'",
        nargs="+",
        metavar="package_spec",
    )
    parser.add_argument(
        "-r",
        "--requirement",
        help="Install from the given requirements file.",
        nargs="*",
        dest="requirement_files",
        metavar="REQUIREMENT_FILE",
        default=[],
    )
    parser.add_argument(
        "-p",
        "-t",
        "--target",
        help="Target directory",
        default=".",
        dest="target_dir",
        metavar="TARGET_DIR",
    )
    parser.add_argument(
        "-i",
        "--index-url",
        help="Custom index URL",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Show more details about the process",
        action="store_true",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        help="Don't show non-error output",
        action="store_true",
    )
    args = parser.parse_args(args=raw_args)

    all_specs = args.specs
    for req_file in args.requirement_files:
        all_specs.extend(_read_requirements(req_file))

    if args.index_url:
        index_urls = [args.index_url]
    else:
        index_urls = DEFAULT_INDEX_URLS

    if args.quiet and args.verbose:
        print("Can't be quiet and verbose at the same time", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        logging_level = logging.DEBUG
    elif args.quiet:
        logging_level = logging.ERROR
    else:
        logging_level = logging.INFO

    logger.setLevel(logging_level)
    logger.propagate = True
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging_level)
    logger.addHandler(console_handler)

    install(all_specs, install_dir=args.target_dir, index_urls=index_urls)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])

import argparse
import csv
import os
import random
import re
from collections import defaultdict
from typing import Dict, List, Tuple

import numpy as np
from IPython import embed
from tqdm import tqdm

import ghcc

# tag -> (date_time, value_at_time)
InfoDict = Dict[str, List[Tuple[str, int]]]
TAGS = ["n_partial", "n_binaries", "n_total"]

parser = argparse.ArgumentParser()
parser.add_argument("log_file")
args = parser.parse_args()


def all_equal(xs) -> bool:
    r"""Returns whether all elements in the list :attr:`xs` are equal."""
    return not xs or all(x == xs[0] for x in xs[1:])


def changed_repos(repo_info: Dict[str, InfoDict]) -> Dict[str, InfoDict]:
    r"""Filters out the repositories in the InfoDict such that not all recorded values are the same."""
    changed = {}
    for name, info in repo_info.items():
        if any(not all_equal([v for _, v in vals]) for vals in info.values()):
            changed[name] = info
    return changed


def analyze_logs(path: str) -> Dict[str, InfoDict]:
    r"""Reads and parse the compilation log generated by ``main.py``, and returns information for each repository."""
    with open(path, "r") as f:
        logs = f.read().split("\n")

    repo_info: Dict[str, InfoDict] = defaultdict(lambda: {tag: [] for tag in TAGS})
    regex = re.compile(r"(?P<date_time>[0-9-]{10} [0-9:]{8}),\d{3} \w+: "
                       r"(?P<n_success>\d+) \((?P<n_partial>\d+)\) out of (?P<n_total>\d+) Makefile\(s\) in "
                       r"(?P<repo_owner>\w+)/(?P<repo_name>\w+) compiled \(partially\), "
                       r"yielding (?P<n_binaries>\d+) binaries")
    for idx, line in enumerate(logs):
        match = regex.search(line)
        if match is not None:
            repo_owner, repo_name = match.group("repo_owner"), match.group("repo_name")
            repo_full_name = f"{repo_owner}/{repo_name}"
            date_time = match.group("date_time")
            for tag in TAGS:
                value = int(match.group(tag))
                repo_info[repo_full_name][tag].append((date_time, value))
    return repo_info


def main():
    ghcc.utils.register_ipython_excepthook()
    random.seed(ghcc.__MAGIC__)
    np.random.seed(ghcc.__MAGIC__)

    repo_info = analyze_logs(args.log_file)
    changed = changed_repos(repo_info)

    # Sample 100 failed repositories.
    repos_with_fail = [repo for repo, info in repo_info.items()
                       if info["n_partial"][-1] < info["n_total"][-1]]
    samples = np.random.choice(len(repos_with_fail), 100, replace=False)
    _repo_samples = [repos_with_fail[x] for x in samples]

    # Remove repositories with more than 50 Makefiles.
    repo_samples = []
    for repo in _repo_samples:
        _, val = repo_info[repo]["n_total"][-1]
        if val <= 50:
            repo_samples.append(repo)
        else:
            print(f"{repo} contains {val} Makefiles, skipping")

    # Clone the repositories.
    for repo in tqdm(repo_samples, desc="Cloning repos"):
        owner, name = repo.split("/")
        ghcc.clone(owner, name, "test_compile")

    # Write repository information into a CSV file.
    # Each line is a separate Makefile.
    db = ghcc.Database()
    with open("repo_samples.csv", "w") as f:
        writer = csv.writer(f)
        writer.writerow(["Repo", "Makefile", "Status", "Failed Reason?"])

        for repo in tqdm(repo_samples, desc="Writing CSV"):
            makefiles = ghcc.find_makefiles(os.path.join("test_compile", repo))
            owner, name = repo.split("/")
            entry = db.get(owner, name)
            success_makefiles = set()
            for makefile_info in entry['makefiles']:
                directory = makefile_info["directory"]
                directory = "/".join([owner, name] + directory.split("/")[4:])
                success_makefiles.add(directory)
            for makefile in makefiles:
                directory = "/".join(makefile.split("/")[1:])
                status = "" if directory in success_makefiles else "Failed"
                writer.writerow([repo, directory, status])
                print(repo, directory, status)


if __name__ == '__main__':
    main()

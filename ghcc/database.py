import json
import os
import sys
from datetime import datetime
from typing import List, Optional

import pymongo
from mypy_extensions import TypedDict

__all__ = [
    "RepoMakefileEntry",
    "RepoEntry",
    "Database",
]


# TODO: Distinguish between failed compilations & makefiles with no yield

class RepoMakefileEntry(TypedDict):
    directory: str  # directory containing the Makefile
    successful: bool  # whether compilation was successful (return code 0)
    num_binaries: int  # number of binaries generated (required because MongoDB cannot aggregate list lengths)
    binaries: List[str]  # list of paths to binaries generated by make operation
    sha256: List[str]  # SHA256 hashes for each binary


class RepoEntry(TypedDict):
    repo_owner: str
    repo_name: str
    clone_successful: bool  # whether the repo has been successfully cloned to the server
    compiled: bool  # whether the repo has been tested for compilation
    num_makefiles: int  # number of compilable Makefiles (required because MongoDB cannot aggregate list lengths)
    makefiles: List[RepoMakefileEntry]  # list of Makefiles that are successfully compiled


class DBConfig(TypedDict):
    host: str
    port: int
    auth_db_name: str
    db_name: str
    collection_name: str
    username: str
    password: str


class Database:
    r"""An abstraction over MongoDB that stores information about repositories.
    """

    def __init__(self, config_file: str = "./database-config.json"):
        r"""Create a connection to the database.
        """
        if not os.path.exists(config_file):
            raise ValueError(f"DB config file not found at '{config_file}'. "
                             f"Please refer to 'database-config-example.json' for the format")
        with open(config_file) as f:
            config: DBConfig = json.load(f)
        missing_keys = [key for key in DBConfig.__annotations__ if key not in config]
        if len(missing_keys) > 0:
            raise ValueError(f"Keys {missing_keys} are missing from the DB config file at '{config_file}'.from "
                             f"Please refer to 'database-config-example.json' for the format")

        self.client = pymongo.MongoClient(
            config['host'], port=config['port'], authSource=config['auth_db_name'],
            username=config['username'], password=config['password'])
        self.collection = self.client[config['db_name']][config['collection_name']]

    def close(self) -> None:
        self.client.close()
        del self.collection

    def get(self, repo_owner: str, repo_name: str) -> Optional[RepoEntry]:
        r"""Get the DB entry corresponding to the specified repository.

        :return: If entry exists, it is returned as a dictionary; otherwise ``None`` is returned.
        """
        return self.collection.find_one({"repo_owner": repo_owner, "repo_name": repo_name})

    def add_repo(self, repo_owner: str, repo_name: str, clone_successful: bool, repo_size: int = -1) -> None:
        r"""Add a new DB entry for the specified repository. Arguments correspond to the first three fields in
        :class:`RepoEntry`. Other fields are set to sensible default values (``False`` and ``[]``).

        :param repo_owner: Owner of the repository.
        :param repo_name: Name of the repository.
        :param clone_successful: Whether the repository was successfully cloned.
        :param repo_size: Size (in bytes) of the cloned repository, or ``-1`` (default) if cloning failed.
        :return: The internal ID of the inserted entry.
        """
        if self.get(repo_owner, repo_name) is None:
            record = {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "clone_successful": clone_successful,
                "repo_size": repo_size,
                "compiled": False,
                "num_makefiles": 0,
                "num_binaries": 0,
                "makefiles": [],
            }
            self.collection.insert_one(record)

    def update_makefile(self, repo_owner: str, repo_name: str, makefiles: List[RepoMakefileEntry],
                        ignore_length_mismatch: bool = False) -> None:
        entry = self.get(repo_owner, repo_name)
        if entry is None:
            raise ValueError(f"Specified repository {repo_owner}/{repo_name} does not exist")
        if not ignore_length_mismatch and len(entry["makefiles"]) not in [0, len(makefiles)]:
            raise ValueError(f"Number of makefiles stored in entry ({len(entry['makefiles'])}) does not "
                             f"match provided list ({len(makefiles)})")
        result = self.collection.update_one({"_id": entry["_id"]}, {"$set": {
            "compiled": True,
            "num_makefiles": len(makefiles),
            "num_binaries": sum(len(makefile["binaries"]) for makefile in makefiles),
            "makefiles": makefiles,
        }})
        assert result.matched_count == 1

    def _aggregate_sum(self, field_name: str) -> int:
        cursor = self.collection.aggregate(
            [{"$match": {"compiled": True}},
             {"$group": {"_id": "$compiled", "total": {"$sum": f"${field_name}"}}}])
        return next(cursor)["total"]

    def count_makefiles(self) -> int:
        return self._aggregate_sum("num_makefiles")

    def count_binaries(self) -> int:
        return self._aggregate_sum("num_binaries")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        confirm = input("This will drop the entire database. Confirm? [y/N] ")
        if confirm.lower() in ["y", "yes"]:
            db = Database()
            db.collection.delete_many({})
            db.close()
            print("Database dropped.")
        else:
            print("Operation cancelled.")

# Standard imports
import json
import os
import re
import shlex
import subprocess
import time

# Local imports
from .checker_base import ValidatorChecker
from .constants import RED_X
from .utils import send_monitor_notification


class GitUpdateError(Exception):
    pass


class ValidatorCheckerGitUpdateBase(ValidatorChecker):
    log_prefix = "CHECK CODE UPDATE"

    def _init_setup(self, options):
        if options.code_repo_path:
            # Get the input repo paths
            self._code_repo_paths = [
                os.path.expanduser(p) for p in options.code_repo_path
            ]
        else:
            self._code_repo_paths = (
                self._get_repo_paths_from_restart_script(options)
                or self._get_repo_paths_from_pm2(options)
                or self._get_repo_path_from_cwd()
            )

    def _get_repo_path_from_cwd(self):
        # Get the repo path from the current working directory
        git_cmd = "git rev-parse --show-toplevel"
        try:
            process = subprocess.run(shlex.split(git_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError:
            self.log_warning(f"Current working directory '{os.getcwd()}' is not a git repository.")
            return []

        cwd_repo_path = process.stdout.decode().strip()

        # TODO: This duplicate code needs to be in a separate function.
        restarter_dir = os.path.dirname(__file__)
        git_cmd = f"git -C {restarter_dir} rev-parse --show-toplevel"
        try:
            process = subprocess.run(shlex.split(git_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            # Should never ever get here
            self.log_warning(f"Could not find restarter git repo from path '{restarter_dir}': {exc}")
        else:
            restarter_repo_path = process.stdout.decode().strip()
            if cwd_repo_path == restarter_repo_path:
                self.log_warning(
                    f"Current working directory repo path is the restarter repo path: '{cwd_repo_path}'"
                )
                return []

        self.log_info(f"Found repo path from current working directory: {cwd_repo_path}")
        return [cwd_repo_path]


    def _get_repo_paths_from_pm2(self, options):
        # Try to get the code repo path from the validator pm2 processes
        # if they exist.
        if not options.pm2_processes:
            return []

        repo_paths = set()

        process = subprocess.run(["pm2", "jlist"], stdout=subprocess.PIPE)
        pm2_output = json.loads(process.stdout)

        for pm2_process in pm2_output:
            pm2_name = pm2_process["name"]
            if pm2_name in options.pm2_processes:
                pm2_cwd = pm2_process["pm2_env"]["pm_cwd"]
                git_cmd = f"git -C {pm2_cwd} rev-parse --show-toplevel"
                try:
                    process = subprocess.run(shlex.split(git_cmd), check=True, stdout=subprocess.PIPE)
                except subprocess.CalledProcessError:
                    continue
                repo_path = process.stdout.decode().strip()
                self.log_info(f"Found repo path from '{pm2_name}' pm2 process: {repo_path}")
                repo_paths.add(repo_path)

        return list(repo_paths)

    def _get_repo_paths_from_restart_script(self, options):
        # Try to get the code repo path from the rsn.sh script.
        cd_regex = re.compile(r"^\s*cd\s+(?P<dir>.+?)\s+")
        repo_paths = set()
        cd_dir = ""

        restart_script = os.path.expanduser(options.restart_script)
        with open(restart_script, "r") as fp:
            script_lines = fp.readlines()

        for line in script_lines:
            regex_match = cd_regex.match(line)
            if not regex_match:
                continue
            cd_dir = os.path.join(
                cd_dir, os.path.expanduser(regex_match.group("dir"))
            )
            git_cmd = f"git -C {cd_dir} rev-parse --show-toplevel"
            try:
                process = subprocess.run(shlex.split(git_cmd), check=True, stdout=subprocess.PIPE)
            except subprocess.CalledProcessError:
                continue
            repo_path = process.stdout.decode().strip()
            self.log_info(f"Found repo path from {restart_script} script: {repo_path}")
            repo_paths.add(repo_path)

        return list(repo_paths)

    def _run(self):
        self.log_info("")
        self.log_info("Checking for code updates.")
        self.log_info("")
        
        if not self._code_repo_paths:
            self.log_error("No valid git repo path. Not checking for code updates.")
            return

        while True:
            do_restart = False
            for code_repo_path in self._code_repo_paths:
                self.log_info("")
                self.log_info(f"Checking repo path: {code_repo_path}")
                self.log_info("")
                if not os.path.isdir(code_repo_path):
                    self.log_error(f"Repo directory path does not exist: {code_repo_path}")
                    continue

                git_command = (
                    f"git -C {code_repo_path}"
                    if code_repo_path != os.getcwd()
                    else "git"
                )
                try:
                    do_restart |= self._check_code_repo(git_command)
                except GitUpdateError:
                    send_monitor_notification(
                        self.log_prefix,
                        f"{RED_X} Failed to update git repo on subnet {self._netuid}"
                    )

            if do_restart:
                self._restart_validator(
                    "Pulled new code from git repo.",
                    force_notify=True
                )

            sleep_interval = 900  # 15 minutes
            self.log_info(f"Sleeping for {sleep_interval} seconds.")
            time.sleep(sleep_interval)

    def _check_code_repo(self, *args, **kwargs):
        raise NotImplementedError


class ValidatorCheckerGitUpdateCommits(ValidatorCheckerGitUpdateBase):

    def _check_code_repo(self, git_command):
        get_cmd = f"{git_command} rev-parse HEAD"
        pull_cmd = f"{git_command} pull --autostash"

        # Get commit then pull then get commit again. First get commit is in case
        # the code was manually pulled while we were waiting. This ensures that
        # we are always comparing the correct commits.
        try:
            process = subprocess.run(shlex.split(get_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{get_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        current_commit = process.stdout.decode().strip()

        try:
            subprocess.run(shlex.split(pull_cmd), check=True)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{pull_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        try:
            process = subprocess.run(shlex.split(get_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{get_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        new_commit = process.stdout.decode().strip()

        self.log_info("")
        self.log_info(f"Current commit: {current_commit}")
        self.log_info(f"New commit: {new_commit}")
        if current_commit != new_commit:
            self.log_info("Commits changed.")
            return True

        self.log_info("Commits are the same. Doing nothing.")
        return False


class ValidatorCheckerGitUpdateTags(ValidatorCheckerGitUpdateBase):

    def _check_code_repo(self, git_command):
        fetch_cmd = f"{git_command} fetch"
        get_cmd = f"{git_command} describe --tags"
        current_cmd = f"{git_command} rev-parse HEAD"
        latest_cmd = f"{git_command} rev-list --tags --max-count=1"
        pull_cmd = f"{git_command} checkout"
        stash_check_cmd = f"{git_command} status --porcelain --untracked-files=no"
        stash_push_cmd = f"{git_command} stash push"
        stash_pop_cmd = f"{git_command} stash pop"

        try:
            subprocess.run(shlex.split(fetch_cmd), check=True)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{fetch_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        try:
            process = subprocess.run(shlex.split(current_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{current_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        current_rev = process.stdout.decode().strip()

        try:
            get_current_cmd = f"{get_cmd} {current_rev}"
            process = subprocess.run(shlex.split(get_current_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{get_current_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        current_tag = process.stdout.decode().strip()

        try:
            process = subprocess.run(shlex.split(latest_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{latest_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        latest_rev = process.stdout.decode().strip()

        try:
            get_latest_cmd = f"{get_cmd} {latest_rev}"
            process = subprocess.run(shlex.split(get_latest_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{get_latest_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        latest_tag = process.stdout.decode().strip()

        self.log_info("")
        self.log_info(f"Current tag: {current_tag}")
        self.log_info(f"Latest tag: {latest_tag}")
        if latest_tag.endswith("-rc"):
            self.log_info("Latest tag is not a release. Doing nothing.")
            return False

        if current_tag == latest_tag:
            self.log_info("Tags are the same. Doing nothing.")
            return False

        self.log_info("Tags are different.")

        # Check if there are local changes.
        try:
            process = subprocess.run(shlex.split(stash_check_cmd), check=True, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{stash_check_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        do_stash = bool(process.stdout.decode().strip())

        # If there are local changes then we need to stash the changes
        # before checking out latest tag.
        if do_stash:
            try:
                subprocess.run(shlex.split(stash_push_cmd), check=True)
            except subprocess.CalledProcessError as exc:
                self.log_error(f"'{stash_push_cmd}' command failed with error: {exc}")
                raise GitUpdateError

        try:
            pull_latest_cmd = f"{pull_cmd} {latest_tag}"
            subprocess.run(shlex.split(pull_latest_cmd), check=True)
        except subprocess.CalledProcessError as exc:
            self.log_error(f"'{pull_latest_cmd}' command failed with error: {exc}")
            raise GitUpdateError

        # If there are local changes then we need to unstash the changes
        # after checking out latest tag.
        if do_stash:
            try:
                subprocess.run(shlex.split(stash_pop_cmd), check=True)
            except subprocess.CalledProcessError as exc:
                self.log_error(f"'{stash_pop_cmd}' command failed with error: {exc}")
                raise GitUpdateError

        self.log_info("Pulled latest tag.")
        return True

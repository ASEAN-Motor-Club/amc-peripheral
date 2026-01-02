"""
Codebase exploration tools for JARVIS.

Provides utilities to search, read, and navigate through the monorepo source code.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional, Any


class CodebaseTools:
    """Tools for exploring and reading the monorepo codebase."""

    def __init__(self, repo_path: str):
        """
        Initialize codebase tools with the repo path.

        Args:
            repo_path: Absolute path to the monorepo root
        """
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists():
            raise ValueError(f"Repo path does not exist: {repo_path}")

        # Directories and patterns to exclude from searches
        self.exclude_patterns = [
            ".git",
            "__pycache__",
            "node_modules",
            ".direnv",
            ".venv",
            "result",
            ".pytest_cache",
            ".ruff_cache",
            "map_tiles",  # Large tile directory in amc-server
            ".DS_Store",
        ]

    def search_files(self, pattern: str, max_results: int = 20) -> list[dict[str, Any]]:
        """
        Search for files matching a glob pattern.

        Args:
            pattern: Glob pattern to search for (e.g., "*.py", "flake.nix", "**/mods.nix")
            max_results: Maximum number of results to return

        Returns:
            List of dicts with 'path' (relative to repo) and 'size' keys
        """
        results = []
        try:
            # Use rglob for recursive search
            for path in self.repo_path.rglob(pattern):
                # Skip excluded directories
                if any(exc in path.parts for exc in self.exclude_patterns):
                    continue

                if path.is_file():
                    rel_path = path.relative_to(self.repo_path)
                    # pyrefly: ignore [bad-argument-type]
                    results.append(
                        {
                            "path": str(rel_path),
                            "size": path.stat().st_size,
                            "type": "file",
                        }
                    )

                    if len(results) >= max_results:
                        break
        except Exception as e:
            return [{"error": f"Search failed: {str(e)}"}]

        return results

    def read_file(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """
        Read contents of a file, optionally with line range.

        Args:
            path: Relative path to file from repo root
            start_line: Start line (1-indexed), inclusive
            end_line: End line (1-indexed), inclusive

        Returns:
            File contents, optionally with line numbers
        """
        try:
            file_path = self.repo_path / path
            # Security: ensure path is within repo
            file_path = file_path.resolve()
            if not str(file_path).startswith(str(self.repo_path.resolve())):
                return f"Error: Path '{path}' is outside the repository"

            if not file_path.exists():
                return f"Error: File '{path}' does not exist"

            if not file_path.is_file():
                return f"Error: '{path}' is not a file"

            # Check file size - limit to 1MB
            max_size = 1 * 1024 * 1024
            if file_path.stat().st_size > max_size:
                return f"Error: File '{path}' is too large (>1MB). Use line range to read specific sections."

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            # Apply line range if specified
            if start_line is not None or end_line is not None:
                start_idx = (start_line - 1) if start_line else 0
                end_idx = end_line if end_line else len(lines)
                lines = lines[start_idx:end_idx]

                # Add line numbers
                result_lines = []
                for i, line in enumerate(lines, start=(start_line or 1)):
                    result_lines.append(f"{i:4d}: {line.rstrip()}")
                return "\n".join(result_lines)
            else:
                # Return full file without line numbers if small enough
                return "".join(lines)

        except UnicodeDecodeError:
            return f"Error: File '{path}' appears to be binary"
        except Exception as e:
            return f"Error reading file: {str(e)}"

    def grep_search(
        self, query: str, path: str = ".", max_results: int = 30
    ) -> list[dict[str, Any]]:
        """
        Search for text pattern using ripgrep.

        Args:
            query: Text pattern to search for
            path: Directory or file path to search in (relative to repo)
            max_results: Maximum number of results to return

        Returns:
            List of dicts with 'file', 'line_number', and 'content' keys
        """
        try:
            search_path = self.repo_path / path

            # Build ripgrep command
            cmd = [
                "rg",
                "--json",
                "--max-count",
                str(max_results),
                "--",
                query,
                str(search_path),
            ]

            # Add exclude patterns
            for pattern in self.exclude_patterns:
                cmd.insert(2, f"--glob=!{pattern}")

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )

            if result.returncode not in [0, 1]:  # 1 = no matches
                return [{"error": f"Search failed: {result.stderr}"}]

            # Parse JSON output
            matches: list[dict] = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    # pyrefly: ignore [import-outside-top-level]
                    data: dict = json.loads(line)
                    if data.get("type") == "match":
                        match_data: dict = data["data"]
                        file_path = Path(match_data["path"]["text"])
                        rel_path = file_path.relative_to(self.repo_path)

                        matches.append(
                            {
                                "file": str(rel_path),
                                "line_number": match_data["line_number"],
                                "content": match_data["lines"]["text"].rstrip(),
                            }
                        )

                        if len(matches) >= max_results:
                            break
                except (json.JSONDecodeError, KeyError):
                    continue

            return matches

        except FileNotFoundError:
            # ripgrep not available - fallback to grep
            return self._fallback_grep(query, path, max_results)
        except subprocess.TimeoutExpired:
            return [{"error": "Search timed out"}]
        except Exception as e:
            return [{"error": f"Search error: {str(e)}"}]

    def _fallback_grep(
        self, query: str, path: str, max_results: int
    ) -> list[dict[str, Any]]:
        """Fallback grep implementation using Python."""
        matches = []
        search_path = self.repo_path / path

        try:
            if search_path.is_file():
                files = [search_path]
            else:
                files = [
                    f
                    for f in search_path.rglob("*")
                    if f.is_file()
                    and not any(exc in f.parts for exc in self.exclude_patterns)
                ]

            for file_path in files:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if query.lower() in line.lower():
                                rel_path = file_path.relative_to(self.repo_path)
                                matches.append(
                                    {
                                        "file": str(rel_path),
                                        "line_number": line_num,
                                        "content": line.rstrip(),
                                    }
                                )
                                if len(matches) >= max_results:
                                    return matches
                except Exception:
                    continue

        except Exception as e:
            return [{"error": f"Fallback search failed: {str(e)}"}]

        return matches

    def list_directory(self, path: str = ".", recursive: bool = False) -> list[dict[str, Any]]:
        """
        List contents of a directory.

        Args:
            path: Path to directory (relative to repo)
            recursive: Whether to list recursively

        Returns:
            List of dicts with 'name', 'type', 'size' (for files) keys
        """
        try:
            dir_path = self.repo_path / path

            # Security check
            dir_path = dir_path.resolve()
            if not str(dir_path).startswith(str(self.repo_path.resolve())):
                return [{"error": f"Path '{path}' is outside the repository"}]

            if not dir_path.exists():
                return [{"error": f"Directory '{path}' does not exist"}]

            if not dir_path.is_dir():
                return [{"error": f"'{path}' is not a directory"}]

            results = []

            if recursive:
                # Recursive listing
                for item in dir_path.rglob("*"):
                    # Skip excluded
                    if any(exc in item.parts for exc in self.exclude_patterns):
                        continue

                    rel_path = item.relative_to(dir_path)
                    entry: dict[str, Any] = {
                        "name": str(rel_path),
                        "type": "directory" if item.is_dir() else "file",
                    }
                    if item.is_file():
                        entry["size"] = item.stat().st_size
                    results.append(entry)

                    # Limit recursive results
                    if len(results) >= 100:
                        results.append(
                            {
                                "warning": "Results truncated at 100 items. Use non-recursive listing for specific subdirectories."
                            }
                        )
                        break
            else:
                # Non-recursive listing
                for item in sorted(dir_path.iterdir()):
                    if item.name in self.exclude_patterns:
                        continue

                    entry: dict[str, Any] = {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                    }
                    if item.is_file():
                        entry["size"] = item.stat().st_size
                    elif item.is_dir():
                        # Count children for directories
                        try:
                            num_children = sum(1 for _ in item.iterdir())
                            entry["num_children"] = num_children
                        except PermissionError:
                            pass
                    results.append(entry)

            return results

        except Exception as e:
            return [{"error": f"List directory failed: {str(e)}"}]

    def nix_hash_url(self, url: str, unpack: bool = True) -> dict[str, Any]:
        """
        Calculate the Nix hash for a URL.

        Uses nix-prefetch-url to download and hash the URL content.
        This is useful for getting hashes for fetchzip, fetchurl, etc.

        Args:
            url: The URL to fetch and hash
            unpack: Whether to unpack the archive (for fetchzip). Default True.

        Returns:
            Dict with 'hash' (SRI format) or 'error' key
        """
        try:
            # Build command - use --unpack for archives (fetchzip)
            cmd = ["nix-prefetch-url", "--type", "sha256"]
            if unpack:
                cmd.append("--unpack")
            cmd.append(url)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for large downloads
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                return {"error": f"nix-prefetch-url failed: {error_msg}"}

            # Get the NAR hash from stdout
            nar_hash = result.stdout.strip()

            # Convert to SRI format for use in Nix
            sri_result = subprocess.run(
                ["nix", "hash", "to-sri", "--type", "sha256", nar_hash],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if sri_result.returncode != 0:
                # Fallback: return the base32 hash if SRI conversion fails
                return {
                    "hash": nar_hash,
                    "format": "base32",
                    "note": "Use this hash directly in Nix expressions",
                }

            sri_hash = sri_result.stdout.strip()
            return {
                "hash": sri_hash,
                "format": "sri",
                "url": url,
                "note": "Use this hash in the 'hash' attribute of fetchzip/fetchurl",
            }

        except subprocess.TimeoutExpired:
            return {"error": "Download timed out (exceeded 5 minutes)"}
        except FileNotFoundError:
            return {
                "error": "nix-prefetch-url not found. Ensure Nix is installed and in PATH."
            }
        except Exception as e:
            return {"error": f"Failed to calculate hash: {str(e)}"}

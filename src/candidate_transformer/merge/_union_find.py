from __future__ import annotations


class UnionFind:
    """Path-compressed, union-by-rank disjoint set.

    Keys are arbitrary strings (group IDs). `find` applies path compression
    so repeated calls are near-O(1). `union` uses rank to keep trees shallow.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: str) -> str:
        """Return the root of x's set, flattening the path as we go."""
        self.add(x)
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> bool:
        """Merge the sets containing x and y.

        Returns True if they were in different sets (a merge actually happened).
        Uses union-by-rank so the taller tree becomes the root, keeping depth
        bounded at O(log n).
        """
        px, py = self.find(x), self.find(y)
        if px == py:
            return False
        if self._rank[px] < self._rank[py]:
            px, py = py, px
        self._parent[py] = px
        if self._rank[px] == self._rank[py]:
            self._rank[px] += 1
        return True

    def groups(self) -> dict[str, list[str]]:
        """Return {root: [all members]} for every current disjoint set."""
        result: dict[str, list[str]] = {}
        for x in self._parent:
            root = self.find(x)
            result.setdefault(root, []).append(x)
        return result

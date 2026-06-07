"""Uniform spatial grid for O(1) nearby-entity queries."""


class SpatialGrid:
    def __init__(self, cell_size: int = 200):
        self.cell_size = cell_size
        self._cells: dict[tuple[int, int], list] = {}

    def _key(self, x: float, y: float) -> tuple[int, int]:
        return (int(x) // self.cell_size, int(y) // self.cell_size)

    def clear(self) -> None:
        self._cells.clear()

    def insert(self, entity) -> None:
        k    = self._key(entity.pos.x, entity.pos.y)
        cell = self._cells.get(k)
        if cell is None:
            self._cells[k] = [entity]
        else:
            cell.append(entity)

    def query_radius(self, pos, radius: float) -> list:
        cs  = self.cell_size
        cx0 = int(pos.x - radius) // cs
        cx1 = int(pos.x + radius) // cs
        cy0 = int(pos.y - radius) // cs
        cy1 = int(pos.y + radius) // cs
        r2  = radius * radius
        out = []
        for gx in range(cx0, cx1 + 1):
            for gy in range(cy0, cy1 + 1):
                for ent in self._cells.get((gx, gy), ()):
                    if ent.pos.distance_squared_to(pos) <= r2:
                        out.append(ent)
        return out

    def query_rect(self, rect) -> list:
        cs  = self.cell_size
        cx0 = rect.left   // cs
        cx1 = rect.right  // cs
        cy0 = rect.top    // cs
        cy1 = rect.bottom // cs
        out = []
        for gx in range(cx0, cx1 + 1):
            for gy in range(cy0, cy1 + 1):
                for ent in self._cells.get((gx, gy), ()):
                    if rect.collidepoint(ent.pos.x, ent.pos.y):
                        out.append(ent)
        return out

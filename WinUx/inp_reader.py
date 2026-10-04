"""Abaqus input-file summary and CPU recommendation logic."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .inp_preferences import INPPreferences


DOF_MAP = {
    "B31": 6, "S4R": 6, "S4": 6, "S3": 6, "S3R": 6,
    "S4RS": 6, "S4RSW": 6, "SAX1": 6, "SAX2": 6, "SAX2T": 6,
    "SC6R": 6, "S8R": 6, "S8RT": 6, "STRI3": 6, "S4R5": 6,
    "STRI65": 6, "S8R5": 6, "S9R5": 6, "SAXA1N": 6,
    "SAXA2N": 6, "SC8R": 6,
    "R3D4": 3, "C3D6": 3, "C3D8R": 3, "C3D8": 3,
    "C3D8I": 3, "C3D10": 3, "C3D10M": 3, "C3D20": 3,
    "C3D20R": 3, "CPS4R": 3, "CAX4R": 3, "CPS6M": 3,
    "CAX6M": 3, "C3D27R": 3, "C3D27RH": 3,
}


@dataclass
class Part:
    name: str
    nodes: int = 0
    elements: int = 0
    dof_per_node: int = 0

    @property
    def dofs(self):
        return self.nodes * self.dof_per_node


@dataclass
class Instance:
    name: str
    part: Part


class INPReader:
    """Parse model size and calculate a configurable CPU recommendation."""

    def __init__(self, content, scale=5000, recommendation=None):
        # Existing callers pass an integer scale as the second argument. Newer
        # callers pass the complete settings dictionary in that same position.
        if isinstance(scale, dict) and recommendation is None:
            recommendation = scale
            scale = recommendation.get("dof_per_core", 5000)
        values = dict(recommendation or {})
        values.setdefault("dof_per_core", scale)
        self.recommendation = INPPreferences.normalize(values)
        self.scale = int(self.recommendation["dof_per_core"])
        self.parts = {}
        self.instances = []
        self._parse(content)

    @staticmethod
    def _options(keyword):
        return {
            match.group(1).casefold(): match.group(2).strip().strip('"')
            for match in re.finditer(
                r'(?:^|,)\s*([\w -]+)\s*=\s*("[^"]*"|[^,]+)',
                keyword,
            )
        }

    @staticmethod
    def _data_count(lines, start):
        count = 0
        index = start
        while index < len(lines):
            value = lines[index].strip()
            if value.startswith("**"):
                index += 1
                continue
            if value.startswith("*"):
                break
            if re.match(r"^\d+\s*,", value):
                count += 1
            index += 1
        return count, index

    def _parse(self, content):
        lines = (
            str(content)
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .split("\n")
        )
        current = None
        index = 0
        while index < len(lines):
            stripped = lines[index].strip()
            lowered = stripped.casefold()
            if lowered.startswith("*part"):
                name = self._options(stripped).get(
                    "name", "Part-{}".format(len(self.parts) + 1)
                )
                current = self.parts.setdefault(name.casefold(), Part(name))
            elif lowered.startswith("*end part"):
                current = None
            elif current is not None and lowered.startswith("*node"):
                count, index = self._data_count(lines, index + 1)
                current.nodes += count
                continue
            elif current is not None and lowered.startswith("*element"):
                options = self._options(stripped)
                element_type = options.get("type", "").upper()
                current.dof_per_node = max(
                    current.dof_per_node, DOF_MAP.get(element_type, 0)
                )
                count, index = self._data_count(lines, index + 1)
                current.elements += count
                continue
            elif lowered.startswith("*instance"):
                options = self._options(stripped)
                part = self.parts.get(options.get("part", "").casefold())
                if part is not None:
                    name = options.get(
                        "name", "Instance-{}".format(len(self.instances) + 1)
                    )
                    self.instances.append(Instance(name, part))
            index += 1

    @property
    def effective_instances(self):
        if self.instances:
            return self.instances
        return [Instance(part.name, part) for part in self.parts.values()]

    @property
    def total_nodes(self):
        return sum(item.part.nodes for item in self.effective_instances)

    @property
    def total_elements(self):
        return sum(item.part.elements for item in self.effective_instances)

    @property
    def total_dofs(self):
        return sum(item.part.dofs for item in self.effective_instances)

    @staticmethod
    def _clamp(value, minimum, maximum):
        return max(int(minimum), min(int(maximum), int(value)))

    def suggested_cores(self):
        settings = self.recommendation
        minimum = settings["minimum_cores"]
        maximum = settings["maximum_cores"]
        factor = settings["dof_per_core"]

        if settings["formula"] == INPPreferences.FORMULA_ADAPTIVE:
            required = max(1, int(math.ceil(float(self.total_dofs) / factor)))
            step = settings["core_step"]
            rounded = int(math.ceil(float(required) / step) * step)
            return self._clamp(rounded, minimum, maximum)

        # Compatibility formula used by earlier WinUX releases. The result is
        # still clamped by the editable minimum and maximum core settings.
        for candidate in (32, 64, 128):
            if self.total_dofs < factor * candidate:
                return self._clamp(candidate, minimum, maximum)
        return maximum

    def recommendation_description(self):
        settings = self.recommendation
        factor = settings["dof_per_core"]
        minimum = settings["minimum_cores"]
        maximum = settings["maximum_cores"]
        if settings["formula"] == INPPreferences.FORMULA_ADAPTIVE:
            return (
                "Adaptive: ceil(DOF / {:,}), rounded to {} cores, "
                "limited to {}-{}"
            ).format(
                factor, settings["core_step"], minimum, maximum
            )
        return (
            "Legacy tiers: 32 / 64 / 128 / {} cores at {:,} DOF/core, "
            "limited to {}-{}"
        ).format(maximum, factor, minimum, maximum)

    def summary(self, file_name):
        if not self.parts:
            raise ValueError("No *Part blocks were found in this INP file.")
        names = ", ".join(item.name for item in self.effective_instances)
        unknown = sorted({
            item.part.name
            for item in self.effective_instances
            if not item.part.dof_per_node
        })
        result = [
            "File: {}".format(file_name),
            "Instance: {}".format(names or "None"),
            "Total nodes: {:,}".format(self.total_nodes),
            "Total elements: {:,}".format(self.total_elements),
            "Estimated DOFs: {:,}".format(self.total_dofs),
            "Suggested cores: {}".format(self.suggested_cores()),
            "Core formula: {}".format(self.recommendation_description()),
        ]
        if unknown:
            result.append(
                "Warning: unknown element type in {}. Its DOFs were counted "
                "as 0.".format(", ".join(unknown))
            )
        return "\n".join(result)
"""Safe YAML loaders with duplicate-key and exact-number handling."""

from decimal import Decimal, InvalidOperation
from typing import cast

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, Node, ScalarNode

from metricproof.domain.numeric import DecimalToken


class UniqueSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys."""


class ExactSafeLoader(UniqueSafeLoader):
    """SafeLoader variant preserving integer and decimal source text."""


def _construct_unique_mapping(
    loader: UniqueSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = cast(object, loader.construct_object(cast(Node, key_node), deep=deep))  # pyright: ignore[reportUnknownMemberType]
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(cast(Node, value_node), deep=deep)  # pyright: ignore[reportUnknownMemberType]
    return mapping


def _construct_decimal(loader: ExactSafeLoader, node: ScalarNode) -> DecimalToken:
    raw_text = loader.construct_scalar(node)
    normalized = raw_text.replace("_", "")
    try:
        value = Decimal(normalized)
    except InvalidOperation as error:
        raise ConstructorError(
            "while constructing an exact number",
            node.start_mark,
            f"unsupported or non-finite YAML number {raw_text!r}",
            node.start_mark,
        ) from error
    if not value.is_finite():
        raise ConstructorError(
            "while constructing an exact number",
            node.start_mark,
            f"non-finite YAML number {raw_text!r} is not supported",
            node.start_mark,
        )
    return DecimalToken(raw_text=raw_text, value=value)


UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
ExactSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
ExactSafeLoader.add_constructor("tag:yaml.org,2002:int", _construct_decimal)
ExactSafeLoader.add_constructor("tag:yaml.org,2002:float", _construct_decimal)


def load_single_yaml(text: str, *, exact_numbers: bool) -> object:
    """Load exactly one safe YAML document."""

    loader_type = ExactSafeLoader if exact_numbers else UniqueSafeLoader
    documents: list[object] = [
        cast(object, document) for document in yaml.load_all(text, Loader=loader_type)
    ]
    if len(documents) != 1:
        raise yaml.YAMLError("exactly one YAML document is supported")
    return documents[0]

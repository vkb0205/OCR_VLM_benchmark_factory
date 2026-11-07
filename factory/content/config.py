"""Typed content configuration shared by all document types."""
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator
import yaml

from factory.contract.taxonomy import ROOT, Taxonomy

KINDS = {'text', 'table', 'chart', 'statement', 'seal', 'signature', 'figure', 'notes', 'kpis',
         'authors', 'article', 'references'}


class FieldConfig(BaseModel):
    id: str
    cat: str
    kind: str = 'text'
    many: tuple[int, int] | None = None
    lines: str | None = None
    columns: list[str] = Field(default_factory=list)
    section: str | None = None
    parent: str | None = None
    guide: str = ''
    lang: str | None = None
    optional: bool = False


class TypeConfig(BaseModel):
    pool: dict = Field(default_factory=dict)
    elements: list[dict] = Field(default_factory=list)
    design: dict = Field(default_factory=dict)
    lang: str
    variables: dict[str, list[Any]]
    prompt: str
    fields: list[FieldConfig]
    language_variable: str | None = None
    document_type: str | None = None
    statements: dict[str, dict] = Field(default_factory=dict)
    language_configs: dict[str, dict] = Field(default_factory=dict, exclude=True)

    def for_lang(self, lang: str) -> "TypeConfig":
        """Return a copy with the configured fields and statements for a language."""
        result = self.model_copy(deep=True)
        language = self.language_configs.get(lang)
        if language:
            result.fields = [FieldConfig.model_validate(item) for item in language.get("fields", result.fields)]
            result.statements = language.get("statements", result.statements)
            result.variables = {**result.variables, **language.get("variables", {})}
        result.lang = lang
        return result


class PromptConfig(BaseModel):
    system: str
    field_kinds: dict[str, Any]
    repair_rounds: int = Field(ge=0, le=10)
    documents: dict[str, TypeConfig]

    @model_validator(mode='after')
    def validate_fields(self):
        taxonomy = Taxonomy()
        for name, config in self.documents.items():
            config.document_type=name
            if config.lang not in {'vi','en','en_vi_mixed'}:
                raise ValueError(f'{name}: invalid document language {config.lang}')
            if config.language_variable is not None:
                if config.language_variable not in config.variables:
                    raise ValueError(f'{name}: unknown language variable {config.language_variable}')
                languages=config.variables[config.language_variable]
                if not languages or any(language not in {'vi','en','en_vi_mixed'} for language in languages):
                    raise ValueError(f'{name}: language variable must contain supported language tags')
            seen = set()
            for field in config.fields:
                prefix = f'{name}.{field.id}'
                if field.id in seen:
                    raise ValueError(f'{prefix}: duplicate field')
                seen.add(field.id)
                if field.cat not in taxonomy.blocks:
                    raise ValueError(f'{prefix}: unknown cat {field.cat}')
                if field.kind not in KINDS:
                    raise ValueError(f'{prefix}: unknown kind {field.kind}')
                if field.kind == 'statement' and field.lines not in config.statements:
                    raise ValueError(f'{prefix}: missing statement {field.lines}')
                if field.many and (field.kind != 'text' or len(field.many) != 2 or not 1 <= field.many[0] <= field.many[1]):
                    raise ValueError(f'{prefix}: invalid many range')
                if field.kind in {'authors', 'article', 'references'} and field.many is not None:
                    raise ValueError(f'{prefix}: {field.kind} fields cannot use many')
                if field.lang is not None and field.lang not in {'vi','en','en_vi_mixed','other'}:
                    raise ValueError(f'{prefix}: invalid block language {field.lang}')
        return self


@lru_cache
def load_config(path=None) -> PromptConfig:
    if path is not None:
        return PromptConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    raw=yaml.safe_load((ROOT/'configs/content.yaml').read_text(encoding="utf-8"))
    documents = {}
    for path in sorted((ROOT/'configs/doc_types').glob('*.yaml')):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        languages = document.get('lang')
        if isinstance(languages, dict):
            document['language_configs'] = languages
            default_lang = 'vi' if 'vi' in languages else next(iter(languages))
            defaults = languages[default_lang]
            document['lang'] = default_lang
            document['fields'] = defaults.get('fields', document.get('fields', []))
            document['statements'] = defaults.get('statements', document.get('statements', {}))
        documents[path.stem] = document
    raw['documents'] = documents
    return PromptConfig.model_validate(raw)

def doc_types():
    return list(load_config().documents)

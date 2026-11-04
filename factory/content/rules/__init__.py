"""Optional per-document-type rules applied after generic shape validation."""
from importlib import import_module
from inspect import signature
import re


def apply_document_rules(config, values, statements, *, variables=None, lang=None):
    """Load a type's rule module by its config key, if that module exists."""
    doc_type=getattr(config,'document_type',None)
    if doc_type is None:
        return
    if not re.fullmatch(r'[a-z][a-z0-9_]*',doc_type):
        raise ValueError('Invalid document type rule name')
    module_name=f'factory.content.rules.{doc_type}'
    try:
        module=import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name==module_name:
            return
        raise
    apply=getattr(module,'apply',None)
    if apply is not None:
        parameters=signature(apply).parameters
        kwargs={}
        if 'variables' in parameters: kwargs['variables']=variables or {}
        if 'lang' in parameters: kwargs['lang']=lang
        apply(config,values,statements,**kwargs)

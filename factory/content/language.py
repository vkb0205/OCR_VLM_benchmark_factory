"""Deterministic language assignment and conservative leakage diagnostics."""
import re,unicodedata

def choose_language(counts,seed,forced=None):
    if forced:return forced
    vi,en=counts.get('vi',0),counts.get('en',0)
    return ('vi' if seed%2 else 'en') if vi==en else ('vi' if vi<en else 'en')

def leakage(text,lang):
    words=re.findall(r'[^\W\d_]+',text.lower(),re.UNICODE)
    if len(words)<8:return False
    accented=sum(any(unicodedata.combining(c) for c in unicodedata.normalize('NFD',w)) for w in words)
    english=sum(w in {'the','and','with','from','this','that','were','are','shall','prospectively'} for w in words)
    vietnamese=sum(w in {'của','và','được','trong','các','với','năm','báo'} for w in words)
    return (english>=2 and accented/len(words)<.1) if lang=='vi' else vietnamese>=2

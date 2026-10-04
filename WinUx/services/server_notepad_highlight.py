"""Viewport syntax highlighting and debounced UI scheduling."""
from __future__ import annotations
from functools import lru_cache
import re


@lru_cache(maxsize=16)
def compiled_patterns(language):
    patterns = []
    if language == "Python":
        keywords = (
            "and|as|assert|async|await|break|class|continue|def|del|elif|else|"
            "except|False|finally|for|from|global|if|import|in|is|lambda|None|"
            "nonlocal|not|or|pass|raise|return|True|try|while|with|yield")
        patterns = [
            (r"#[^\n]*", "syntax_comment", re.MULTILINE),
            (r"(?s)(?:'''.*?'''|\"\"\".*?\"\"\")", "syntax_string", 0),
            (r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", "syntax_string", 0),
            (r"\b(?:{})\b".format(keywords), "syntax_keyword", 0),
            (r"\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b", "syntax_number", 0),
        ]
    elif language == "Abaqus INP":
        patterns = [
            (r"(?m)^\*\*.*$", "syntax_comment", 0),
            (r"(?m)^\*(?!\*)[^,\n]*", "syntax_keyword", 0),
            (r"(?m)(?<=,)[ \t]*[A-Za-z][A-Za-z0-9 _-]*(?==)", "syntax_parameter", 0),
            (r"\b[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?\b", "syntax_number", 0),
        ]
    elif language == "JSON":
        patterns = [
            (r'"(?:\\.|[^"\\])*"(?=\s*:)', "syntax_key", 0),
            (r'"(?:\\.|[^"\\])*"', "syntax_string", 0),
            (r"\b(?:true|false|null)\b", "syntax_keyword", 0),
            (r"\b-?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?\b", "syntax_number", 0),
        ]
    elif language == "XML/HTML":
        patterns = [
            (r"(?s)<!--.*?-->", "syntax_comment", 0),
            (r"</?[A-Za-z][^>]*?>", "syntax_keyword", 0),
            (r'"(?:\\.|[^"\\])*"', "syntax_string", 0),
        ]
    elif language == "C/C++":
        keywords = (
            "alignas|alignof|auto|bool|break|case|catch|char|class|const|constexpr|"
            "continue|default|delete|do|double|else|enum|explicit|extern|false|float|"
            "for|friend|if|inline|int|long|namespace|new|nullptr|operator|private|"
            "protected|public|return|short|signed|sizeof|static|struct|switch|template|"
            "this|throw|true|try|typedef|typename|union|unsigned|using|virtual|void|volatile|while")
        patterns = [
            (r"(?s)/\*.*?\*/|//[^\n]*", "syntax_comment", 0),
            (r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", "syntax_string", 0),
            (r"\b(?:{})\b".format(keywords), "syntax_keyword", 0),
            (r"(?m)^\s*#\s*\w+", "syntax_directive", 0),
            (r"\b(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?)\b", "syntax_number", 0),
        ]
    elif language == "Fortran":
        keywords = (
            "program|module|subroutine|function|implicit|none|integer|real|double|precision|"
            "character|logical|type|contains|call|if|then|else|elseif|endif|do|enddo|select|"
            "case|where|allocate|deallocate|return|stop|use|only|interface|end|kind")
        patterns = [
            (r"(?m)!.*$", "syntax_comment", 0),
            (r"(?:'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", "syntax_string", 0),
            (r"(?i)\b(?:{})\b".format(keywords), "syntax_keyword", 0),
            (r"\b\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?\b", "syntax_number", 0),
        ]
    elif language == "Shell":
        patterns = [
            (r"(?m)#[^\n]*$", "syntax_comment", 0),
            (r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")", "syntax_string", 0),
            (r"\b(?:if|then|else|elif|fi|for|while|do|done|case|esac|function|in|export|local)\b", "syntax_keyword", 0),
            (r"\$\{?\w+\}?", "syntax_parameter", 0),
        ]
    elif language == "YAML":
        patterns = [
            (r"(?m)#[^\n]*$", "syntax_comment", 0),
            (r"(?m)^\s*[A-Za-z0-9_.-]+(?=\s*:)", "syntax_key", 0),
            (r"(?:'(?:''|[^'])*'|\"(?:\\.|[^\"\\])*\")", "syntax_string", 0),
            (r"\b(?:true|false|null|yes|no|on|off)\b", "syntax_keyword", re.IGNORECASE),
            (r"\b-?\d+(?:\.\d+)?\b", "syntax_number", 0),
        ]

    return tuple((re.compile(pattern, flags), tag) for pattern, tag, flags in patterns)


class ServerNotepadHighlighter:
    MAX_CACHE_CHARS = 200_000

    def __init__(self, view):
        self.view = view

    def _configure_syntax_tags(self, doc):
        doc.highlight_snapshot = None
        text = doc.text
        text.tag_configure("syntax_comment", foreground="#008000")
        text.tag_configure("syntax_string", foreground="#a31515")
        text.tag_configure("syntax_keyword", foreground="#0000ff")
        text.tag_configure("syntax_number", foreground="#098658")
        text.tag_configure("syntax_directive", foreground="#af00db")
        text.tag_configure("syntax_parameter", foreground="#795e26")
        text.tag_configure("syntax_key", foreground="#0451a5")
        text.tag_configure("search_match", background="#fff2a8")

    def _schedule_highlight(self, doc, immediate=False):
        if not doc.loaded:
            return
        doc.highlight_generation += 1
        generation = doc.highlight_generation
        if doc.highlight_after is not None:
            try:
                self.view.root.after_cancel(doc.highlight_after)
            except Exception:
                pass
        delay = 0 if immediate else (320 if doc.performance_mode else 180)
        def deliver():
            if generation == doc.highlight_generation:
                self._highlight_document(doc)
        doc.highlight_after = self.view.root.after(delay, deliver)

    def _highlight_document(self, doc):
        doc.highlight_after = None
        if doc.text is None or not doc.loaded:
            return
        # Notepad++ lexes the visible region incrementally.  Do the same here:
        # highlight only the viewport plus a generous line margin instead of
        # removing/rebuilding tags across a multi-megabyte Tk buffer.
        text = doc.text
        try:
            first_visible = int(text.index("@0,0").split(".")[0])
            last_visible = int(text.index("@0,{}".format(max(1, text.winfo_height()))).split(".")[0])
            first_line = max(1, first_visible - 80)
            last_line = max(first_line + 1, last_visible + 160)
            start_index = "{}.0".format(first_line)
            end_index = "{}.0 lineend".format(last_line)
            sample = text.get(start_index, end_index)
        except Exception:
            return
        language = doc.language
        signature = (id(text), getattr(doc, "index_generation", 0), language,
                     start_index, end_index, sample)
        if getattr(doc, "highlight_snapshot", None) == signature:
            return
        for tag in (
                "syntax_comment", "syntax_string", "syntax_keyword",
                "syntax_number", "syntax_directive", "syntax_parameter",
                "syntax_key"):
            text.tag_remove(tag, start_index, end_index)

        for pattern, tag in compiled_patterns(language):
            try:
                for match in pattern.finditer(sample):
                    start = "{}+{}c".format(start_index, match.start())
                    end = "{}+{}c".format(start_index, match.end())
                    text.tag_add(tag, start, end)
            except re.error:
                continue
        doc.highlight_snapshot = signature if len(sample) <= self.MAX_CACHE_CHARS else None

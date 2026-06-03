"""Tests for the text-mode parser.

Covers:
- Parsing assistant text content
- Parsing single and multiple tool calls
- Handling invalid JSON
- Handling missing tags
- ParseResult structure
"""

from __future__ import annotations

import pytest

from pycodeagent.agent.parser import parse_assistant_response


class TestParseAssistantContent:
    """Tests for extracting assistant text."""

    def test_extracts_assistant_text(self):
        """Should extract text from <assistant> tags."""
        text = "<assistant>\nI will inspect the repository.\n</assistant>"
        result = parse_assistant_response(text)
        assert result.ok
        assert result.assistant_content == "I will inspect the repository."
        assert not result.has_tool_calls

    def test_no_assistant_tags_uses_full_text(self):
        """Without tags, full text is assistant content (if no tool calls)."""
        text = "This is my final answer."
        result = parse_assistant_response(text)
        assert result.ok
        assert result.assistant_content == "This is my final answer."
        assert not result.has_tool_calls

    def test_multiline_assistant_text(self):
        """Should handle multiline assistant content."""
        text = """<assistant>
I will:
1. List files
2. Read the main file
3. Fix the bug
</assistant>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert "I will:" in result.assistant_content
        assert "Fix the bug" in result.assistant_content


class TestParseSingleToolCall:
    """Tests for parsing a single tool call."""

    def test_single_tool_call(self):
        """Should parse one tool call."""
        text = """<assistant>
I will list the files.
</assistant>
<|tool|>
{"id":"call_1","name":"list_files","arguments":{"path":"."}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert result.assistant_content == "I will list the files."
        assert result.has_tool_calls
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.id == "call_1"
        assert call.name == "list_files"
        assert call.arguments == {"path": "."}

    def test_tool_call_without_assistant_text(self):
        """Should parse tool call even without assistant text."""
        text = """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"foo.py"}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert result.assistant_content == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"

    def test_compat_tool_call_without_id(self):
        """Compatibility <tool_call> blocks should parse with synthesized ids."""
        text = """<tool_call>
{"name":"read_file","arguments":{"path":"foo.py"}}
</tool_call>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].id == "compat_call_1"

    def test_compat_tool_call_with_nested_wrapper_tags(self):
        """Compatibility parser should recover the JSON object from nested tags."""
        text = """<tool_call>
<call>
<search_code>
{"name":"search_code","arguments":{"query":"def add"}}
</call>
</tool_call>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search_code"
        assert result.tool_calls[0].arguments == {"query": "def add"}

    def test_compat_tool_call_with_tool_name_and_arguments_tags(self):
        """Compatibility parser should handle split tool_name/arguments tags."""
        text = """<tool_call>
<tool_name>search_code</tool_name>
<arguments>
{"query": "def add"}
</arguments>
</tool_call>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search_code"
        assert result.tool_calls[0].arguments == {"query": "def add"}


class TestParseMultipleToolCalls:
    """Tests for parsing multiple tool calls."""

    def test_multiple_tool_calls(self):
        """Should parse multiple tool calls in sequence."""
        text = """<assistant>
I will inspect the repository.
</assistant>
<|tool|>
{"id":"call_1","name":"list_files","arguments":{"path":"."}}
<|end|>
<|tool|>
{"id":"call_2","name":"read_file","arguments":{"path":"src/main.py"}}
<|end|>
<|tool|>
{"id":"call_3","name":"search_code","arguments":{"query":"TODO"}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert len(result.tool_calls) == 3
        assert result.tool_calls[0].name == "list_files"
        assert result.tool_calls[1].name == "read_file"
        assert result.tool_calls[2].name == "search_code"

    def test_multiple_calls_with_varied_args(self):
        """Should handle varied argument types."""
        text = """<|tool|>
{"id":"c1","name":"read_file","arguments":{"path":"test.py","start_line":10,"end_line":50}}
<|end|>
<|tool|>
{"id":"c2","name":"apply_patch","arguments":{"diff":"--- a/a\\n+++ b/a\\n"}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].arguments["start_line"] == 10
        assert result.tool_calls[1].arguments["diff"] == "--- a/a\n+++ b/a\n"

    def test_mimo_style_tool_sequence(self):
        """Mimo-style <tool_call>/<tool_result> text should still yield tool calls."""
        text = """<tool_call>
{"name": "search_code", "arguments": {"pattern": "def add"}}
</tool_call>
<tool_result>
./app.py: def add(a, b):
</tool_result>
<tool_call>
{"name": "read_file", "arguments": {"path": "app.py"}}
</tool_call>
<tool_result>
def add(a, b):
    return a - b
</tool_result>
<tool_call>
{"name": "finish", "arguments": {"answer": "Done"}}
</tool_call>

Done!"""
        result = parse_assistant_response(text)
        assert result.ok
        assert len(result.tool_calls) == 3
        assert [call.name for call in result.tool_calls] == [
            "search_code",
            "read_file",
            "finish",
        ]
        assert "Done!" in result.assistant_content


class TestParseNoToolCalls:
    """Tests for responses without tool calls."""

    def test_no_tool_calls(self):
        """Should handle response with no tool calls."""
        text = "<assistant>\nThe task is complete.\n</assistant>"
        result = parse_assistant_response(text)
        assert result.ok
        assert not result.has_tool_calls
        assert result.tool_calls == []

    def test_empty_response(self):
        """Should handle empty response."""
        result = parse_assistant_response("")
        assert result.ok
        assert result.assistant_content == ""
        assert not result.has_tool_calls


class TestParseErrors:
    """Tests for parse error handling."""

    def test_invalid_json(self):
        """Invalid JSON should produce parse error, not exception."""
        text = """<|tool|>
{"id":"call_1","name":"list_files","arguments":{invalid}}
<|end|>"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert result.has_parse_errors
        assert len(result.parse_errors) == 1
        assert "Invalid JSON" in result.parse_errors[0]

    def test_missing_id_field(self):
        """Missing 'id' field should produce parse error."""
        text = """<|tool|>
{"name":"list_files","arguments":{"path":"."}}
<|end|>"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert any("missing required field 'id'" in e for e in result.parse_errors)

    def test_missing_name_field(self):
        """Missing 'name' field should produce parse error."""
        text = """<|tool|>
{"id":"c1","arguments":{"path":"."}}
<|end|>"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert any("missing required field 'name'" in e for e in result.parse_errors)

    def test_missing_arguments_field(self):
        """Missing 'arguments' field should produce parse error."""
        text = """<|tool|>
{"id":"c1","name":"list_files"}
<|end|>"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert any("missing required field 'arguments'" in e for e in result.parse_errors)

    def test_arguments_not_object(self):
        """Arguments must be an object."""
        text = """<|tool|>
{"id":"c1","name":"list_files","arguments":"not an object"}
<|end|>"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert any("must be an object" in e for e in result.parse_errors)

    def test_empty_tool_block(self):
        """Empty tool block should produce error."""
        text = """<|tool|>
<|end|>"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert any("Empty tool call block" in e for e in result.parse_errors)

    def test_partial_errors_still_parse_good_calls(self):
        """Should parse valid calls even if some are invalid."""
        text = """<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}
<|end|>
<|tool|>
{"id":"c2","name":"bad","arguments":not_valid}
<|end|>
<|tool|>
{"id":"c3","name":"read_file","arguments":{"path":"a.py"}}
<|end|>"""
        result = parse_assistant_response(text)
        # Should have one error and two valid calls
        assert len(result.parse_errors) == 1
        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].name == "list_files"
        assert result.tool_calls[1].name == "read_file"


class TestParseResultProperties:
    """Tests for ParseResult helper properties."""

    def test_has_tool_calls_true(self):
        """has_tool_calls should be True when calls exist."""
        text = """<|tool|>
{"id":"c1","name":"finish","arguments":{}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.has_tool_calls is True

    def test_has_tool_calls_false(self):
        """has_tool_calls should be False when no calls."""
        result = parse_assistant_response("<assistant>Done</assistant>")
        assert result.has_tool_calls is False

    def test_has_parse_errors_true(self):
        """has_parse_errors should be True on errors."""
        text = """<|tool|>
{"invalid": true}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.has_parse_errors is True

    def test_has_parse_errors_false(self):
        """has_parse_errors should be False when ok."""
        text = """<|tool|>
{"id":"c1","name":"finish","arguments":{}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.has_parse_errors is False


class TestMalformedTagErrors:
    """Tests for unclosed/malformed tag detection."""

    def test_unclosed_assistant_tag(self):
        """Unclosed <assistant> tag should return parse error."""
        text = "<assistant>\nThis has no closing tag."
        result = parse_assistant_response(text)
        assert not result.ok
        assert result.has_parse_errors
        assert any("Unclosed <assistant>" in e for e in result.parse_errors)

    def test_unclosed_tool_block(self):
        """Unclosed <|tool|> block should return parse error."""
        text = """<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert result.has_parse_errors
        assert any("Unclosed tool block" in e for e in result.parse_errors)

    def test_assistant_ok_but_tool_block_unclosed(self):
        """Valid assistant but unclosed tool block should return parse error."""
        text = """<assistant>
I will list files.
</assistant>
<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert result.has_parse_errors
        assert any("Unclosed tool block" in e for e in result.parse_errors)

    def test_multiple_tool_starts_one_missing_end(self):
        """Multiple <|tool|> with one missing <|end|> should return error."""
        text = """<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}
<|end|>
<|tool|>
{"id":"c2","name":"read_file","arguments":{"path":"foo.py"}}"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert result.has_parse_errors
        assert any("Unclosed tool block" in e for e in result.parse_errors)

    def test_unclosed_compat_tool_block(self):
        """Unclosed <tool_call> compatibility block should return parse error."""
        text = """<tool_call>
{"name":"read_file","arguments":{"path":"foo.py"}}"""
        result = parse_assistant_response(text)
        assert not result.ok
        assert any("Unclosed compatibility tool block" in e for e in result.parse_errors)

    def test_valid_format_still_works(self):
        """Valid format with proper closing tags should work."""
        text = """<assistant>
I will inspect the repository.
</assistant>
<|tool|>
{"id":"c1","name":"list_files","arguments":{"path":"."}}
<|end|>"""
        result = parse_assistant_response(text)
        assert result.ok
        assert not result.has_parse_errors
        assert result.assistant_content == "I will inspect the repository."
        assert len(result.tool_calls) == 1

    def test_plain_text_without_tags_still_works(self):
        """Plain text without any tags should still work."""
        text = "This is my final answer."
        result = parse_assistant_response(text)
        assert result.ok
        assert not result.has_parse_errors
        assert result.assistant_content == "This is my final answer."

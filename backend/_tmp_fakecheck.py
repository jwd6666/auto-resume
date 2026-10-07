from app.api.agent.chat import _detect_fake_tool_call as d

cases = {
    "xml_read_expect_True": d({"content": "let me read\n<read_file>\n<path>a.html</path>\n</read_file>"}),
    "replace_in_file_expect_True": d({"content": "<replace_in_file><old_string>x</old_string></replace_in_file>"}),
    "plain_toolname_no_tag_expect_False": d({"content": "patch_file is the tool to edit files"}),
    "normal_chat_expect_False": d({"content": "resume looks good, add more project detail please"}),
    "css_advice_expect_False": d({"content": "you can use CSS font-size property to enlarge text"}),
    "word_function_plain_expect_False": d({"content": "the function of this section is summary"}),
}
for k, v in cases.items():
    print(k, "=>", v)

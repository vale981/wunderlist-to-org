#!/usr/bin/env python

import sys
import datetime
import json
import io
from collections import namedtuple
from contextlib import contextmanager
import re


def _format_org_date(date):
    return date.strftime("%Y-%m-%d %a %H:%M")


def sanitize_text(text):
    star_re = re.compile(r"^\*+")
    star_re.sub("+", text)

    return text


class OrgWriter:
    def __init__(self, level=0):
        self._level = level
        self._org_string = ""

    def emit(self, message="", newline=True):
        """Emit the message keep it simple for now."""

        if newline:
            message += "\n"

        self._org_string += message

        return self

    def get_org_string(self):
        return self._org_string

    @contextmanager
    def new_level(self, level=None):
        if not level:
            level = self._level + 1

        old_level = self._level

        self.set_level(level)
        yield self._level
        self.set_level(old_level)

    @contextmanager
    def drawer(self, name):
        self.emit(f":{name.upper()}:")
        yield self
        self.emit(f":END:")

    ###########################################################################
    #                             Fluent Interface                            #
    ###########################################################################

    def raise_level(self):
        self._level += 1

        return self

    def lower_level(self):
        if self._level > 0:
            self._level -= 1

        return self

    def set_level(self, level):
        if level < 0:
            raise RuntimeError("Heading levels have to be positive.")

        self._level = level

        return self

    def emit_node_title(self, title, todo_state=None, tags=None):
        out_title = "".join(["*" for _ in range(self._level + 1)])

        if todo_state:
            out_title += f" {todo_state.upper()}"

        out_title += f" {title}"

        if tags:
            for i, tag in enumerate(tags):
                tags[i] = tag.upper()

            out_title += f" :{':'.join(tags)}:"

        return self.emit(out_title)

    def emit_timestamp(self, date, timestamp_type=None, active=True, newline=True):
        if not date:
            return self

        stamp = f"{timestamp_type.upper()}: " if timestamp_type else ""

        formated_date = _format_org_date(date)
        stamp += f"<{formated_date}>" if active else f"[{formated_date}]"

        return self.emit(stamp, newline)

    def emit_node(
        self,
        title,
        content=None,
        tags=None,
        timestamp=None,
        timestamp_type=None,
        todo_state=None,
    ):
        self.emit_node_title(title, todo_state, tags)
        self.emit_timestamp(timestamp, timestamp_type)

        if content:
            self.emit(content)

        return self

    def emit_content(self, content):
        self.emit(sanitize_text(content))
        return self.emit()

    def emit_list_item(self, text):
        return self.emit(f" - {text}")

    def emit_property(self, name, value=None):
        self.emit(f":{name.upper()}: ", newline=False)

        return self.emit(value) if value else self


def convert_wunderlist(filename):
    with io.open(filename, "r", encoding="utf-8-sig") as wunder_file:
        wunder_data = json.loads(wunder_file.read())

    if not wunder_data:
        raise RuntimeError("Could not read wunderlist data.")

    writer = OrgWriter()

    for todo_list in wunder_data:
        convert_wunderlist_list(writer, todo_list)

    return writer.get_org_string()


def convert_wunderlist_list(writer, todo_list):
    title, tags = convert_wunderlist_title(todo_list["title"])

    if todo_list["folder"]:
        tags.append(todo_list["folder"]["title"])

    writer.emit_node_title(
        title, tags=tags,
    )

    with writer.new_level():
        for task in todo_list["tasks"]:
            convert_wunderlist_task(writer, task)


def parse_wunderlist_date(date_str):
    if not date_str:
        return None

    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        pass

    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass

    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        pass

    return None


def convert_wunderlist_person(person):
    return f"[[mailto:{person['email']}][{person['name']}]]"


def convert_wunderlist_title(title):
    tag_re = re.compile(r"#(.*?(?:\s+|$))", re.MULTILINE)
    tags = [tag[:-1] for tag in tag_re.findall(title)]
    title = tag_re.sub(r"\1", title)

    return title, tags


def convert_wunderlist_task(writer, task):
    title, tags = convert_wunderlist_title(task["title"])
    writer.emit_node(
        title,
        todo_state="next"
        if task["starred"]
        else ("done" if task["completed"] else "todo"),
        timestamp=parse_wunderlist_date(task["dueDate"]),
        timestamp_type="deadline",
        tags=tags,
    )

    with writer.drawer("properties"):
        writer.emit_property("created-by", convert_wunderlist_person(task["createdBy"]))

        if task["createdAt"]:
            writer.emit_property("created")
            writer.emit_timestamp(
                parse_wunderlist_date(task["createdAt"]), active=False
            )

        if task["completedBy"]:
            writer.emit_property(
                "COMPLETED-BY", convert_wunderlist_person(task["completedBy"])
            )

        if task["completedAt"]:
            writer.emit_property("completed")
            writer.emit_timestamp(
                parse_wunderlist_date(task["completedAt"]), active=False
            )

        if task["reminders"]:
            writer.emit_property("reminders")
            first = True
            for reminder in task["reminders"]:
                if first:
                    first = False
                else:
                    writer.emit(" ", newline=False)

                writer.emit_timestamp(
                    parse_wunderlist_date(reminder["remindAt"]), newline=False
                )

            writer.emit()

        if task["assignee"]:
            writer.emit_property(
                "assignee", convert_wunderlist_person(task["assignee"])
            )

    for note in task["notes"]:
        writer.emit_content(note["content"])

    if task["comments"]:
        with writer.new_level():
            writer.emit_node_title("Comments")
            for comment in task["comments"]:
                convert_wunderlist_comment(writer, comment)

        writer.emit()

    if task["files"]:
        with writer.new_level():
            writer.emit_node_title("Files")
            for w_file in task["files"]:
                convert_wunderlist_file(writer, w_file)

        writer.emit()


def convert_wunderlist_comment(writer, comment):
    comment_text = convert_wunderlist_person(comment["author"])
    comment_text += f": {comment['text']}"
    writer.emit_list_item(comment_text)


def convert_wunderlist_file(writer, w_file):
    writer.emit_list_item(f"[[file:{w_file['filePath']}][{w_file['fileName']}]]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} [input-file]")
        sys.exit(1)

    print(convert_wunderlist(sys.argv[1]))

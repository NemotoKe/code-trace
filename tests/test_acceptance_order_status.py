from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_codewiki(*args):
    return subprocess.run(
        [sys.executable, "-m", "codewiki"] + list(args),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_file(root, relative_path, contents):
    path = os.path.join(root, relative_path)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(contents)


class OrderStatusAcceptanceTests(unittest.TestCase):
    def test_order_status_write_path_is_answerable_from_cli(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-order-status-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-order-status-out-") as out:
            write_file(
                root,
                "src/shop/OrderServlet.java",
                "package shop;\n"
                "import javax.servlet.http.HttpServlet;\n"
                "import javax.servlet.http.HttpServletRequest;\n"
                "import javax.servlet.http.HttpServletResponse;\n"
                "public class OrderServlet extends HttpServlet {\n"
                "    private OrderService service;\n"
                "    @Override\n"
                "    protected void doPost(HttpServletRequest req, HttpServletResponse res) {\n"
                "        String id = req.getParameter(\"id\");\n"
                "        service.cancel(id);\n"
                "    }\n"
                "}\n",
            )
            write_file(
                root,
                "src/shop/OrderService.java",
                "package shop;\n"
                "public class OrderService {\n"
                "    private OrderRepository repository;\n"
                "    public void cancel(String orderId) { repository.updateStatus(orderId, \"CANCELLED\"); }\n"
                "    public void pay(String orderId) { repository.updateStatus(orderId, \"PAID\"); }\n"
                "}\n",
            )
            write_file(
                root,
                "src/shop/OrderRepository.java",
                "package shop;\n"
                "import org.springframework.jdbc.core.JdbcTemplate;\n"
                "public class OrderRepository {\n"
                "    private JdbcTemplate jdbc;\n"
                "    public void updateStatus(String orderId, String status) {\n"
                "        jdbc.update(\"UPDATE ORDER SET STATUS = ? WHERE ID = ?\", status, orderId);\n"
                "    }\n"
                "    public String findStatus(String orderId) {\n"
                "        return jdbc.queryForObject(\"SELECT STATUS FROM ORDER WHERE ID = ?\", String.class, orderId);\n"
                "    }\n"
                "}\n",
            )
            write_file(
                root,
                "src/shop/BatchMain.java",
                "package shop;\n"
                "public class BatchMain {\n"
                "    public static void main(String[] args) {\n"
                "        OrderService service = new OrderService();\n"
                "        service.pay(args[0]);\n"
                "    }\n"
                "}\n",
            )

            indexed = run_codewiki("index", root, "--out", out)
            self.assertEqual(
                0,
                indexed.returncode,
                "index stdout:\n%s\nindex stderr:\n%s"
                % (indexed.stdout, indexed.stderr),
            )

            write_query = run_codewiki(
                "column", "ORDER.STATUS", "--out", out, "--write", "--json"
            )
            self.assertEqual(0, write_query.returncode, write_query.stderr)
            write_payload = json.loads(write_query.stdout)
            self.assertEqual(1, write_payload["count"])
            self.assertEqual(1, len(write_payload["results"]))
            self.assertEqual(
                {
                    "method_fqn": "shop.OrderRepository.updateStatus",
                    "verb": "update",
                    "access": "WRITE",
                },
                {
                    key: write_payload["results"][0][key]
                    for key in ("method_fqn", "verb", "access")
                },
            )

            read_query = run_codewiki(
                "column", "ORDER.STATUS", "--out", out, "--read", "--json"
            )
            self.assertEqual(0, read_query.returncode, read_query.stderr)
            read_payload = json.loads(read_query.stdout)
            self.assertEqual(1, read_payload["count"])
            self.assertEqual(1, len(read_payload["results"]))
            self.assertEqual(
                "shop.OrderRepository.findStatus",
                read_payload["results"][0]["method_fqn"],
            )
            self.assertEqual("select", read_payload["results"][0]["verb"])
            self.assertEqual("READ", read_payload["results"][0]["access"])

            callers_query = run_codewiki(
                "callers", "shop.OrderRepository.updateStatus",
                "--out", out, "--json",
            )
            self.assertEqual(0, callers_query.returncode, callers_query.stderr)
            callers_payload = json.loads(callers_query.stdout)
            self.assertEqual(2, callers_payload["count"])
            self.assertEqual(
                [
                    ("shop.OrderService.cancel", "CONFIRMED"),
                    ("shop.OrderService.pay", "CONFIRMED"),
                ],
                [
                    (result["caller_fqn"], result["confidence"])
                    for result in callers_payload["results"]
                ],
            )

            trace_query = run_codewiki(
                "trace-up", "shop.OrderRepository.updateStatus",
                "--out", out, "--entrypoints", "--json",
            )
            self.assertEqual(0, trace_query.returncode, trace_query.stderr)
            trace_payload = json.loads(trace_query.stdout)
            self.assertEqual(2, trace_payload["count"])
            self.assertEqual(2, len(trace_payload["results"]))
            by_entrypoint = {
                result["fqn"]: result for result in trace_payload["results"]
            }
            self.assertEqual(
                {
                    "shop.OrderServlet.doPost",
                    "shop.BatchMain.main",
                },
                set(by_entrypoint),
            )
            self.assertEqual("servlet", by_entrypoint[
                "shop.OrderServlet.doPost"
            ]["kind"])
            self.assertEqual("main", by_entrypoint[
                "shop.BatchMain.main"
            ]["kind"])
            self.assertEqual(
                [
                    "shop.OrderServlet.doPost",
                    "shop.OrderService.cancel",
                    "shop.OrderRepository.updateStatus",
                ],
                [
                    node["fqn"]
                    for node in by_entrypoint["shop.OrderServlet.doPost"]["chain"]
                ],
            )
            self.assertEqual(
                [
                    "shop.BatchMain.main",
                    "shop.OrderService.pay",
                    "shop.OrderRepository.updateStatus",
                ],
                [
                    node["fqn"]
                    for node in by_entrypoint["shop.BatchMain.main"]["chain"]
                ],
            )

            missing_query = run_codewiki(
                "column", "ORDER.NOTHING", "--out", out, "--json"
            )
            self.assertEqual(0, missing_query.returncode, missing_query.stderr)
            missing_payload = json.loads(missing_query.stdout)
            self.assertEqual(0, missing_payload["count"])
            self.assertEqual([], missing_payload["results"])


if __name__ == "__main__":
    unittest.main()

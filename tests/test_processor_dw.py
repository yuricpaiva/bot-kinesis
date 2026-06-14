from decimal import Decimal

from src.mappers import map_order_picture
from src.processor_dw import UPSERT_VENDA_SQL, save_mapped_order
from tests.test_mappers import TZ, base_payload


class FakeCursor:
    def __init__(self):
        self.commands = []
        self.fetchone_rows = []
        self.rowcount = -1
        self.existing_venda_id = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.commands.append((normalized, params))
        self.rowcount = -1

        if "INSERT INTO dw.vendas" in normalized:
            inserted = not any(
                "INSERT INTO dw.vendas" in command_sql
                for command_sql, _ in self.commands[:-1]
            )
            self.fetchone_rows.append({"id": 10, "inserted": inserted, "cancelado": False})
            self.existing_venda_id = 10
            return

        if normalized.startswith("SELECT id FROM dw.vendas"):
            row = (
                {"id": self.existing_venda_id}
                if self.existing_venda_id is not None
                else None
            )
            self.fetchone_rows.append(row)
            return

        if normalized.startswith("DELETE FROM dw.pagamentos"):
            self.rowcount = 1 if self.existing_venda_id is not None else 0
            return

        if normalized.startswith("DELETE FROM dw.produtos"):
            self.rowcount = 1 if self.existing_venda_id is not None else 0
            return

        if normalized.startswith("DELETE FROM dw.cancelamentos"):
            self.rowcount = 0
            return

        if normalized.startswith("DELETE FROM dw.vendas"):
            self.rowcount = 1 if self.existing_venda_id is not None else 0
            self.existing_venda_id = None

    def fetchone(self):
        return self.fetchone_rows.pop(0)


def test_save_mapped_order_substitui_filhos_quando_mesma_venda_chega_de_novo():
    cursor = FakeCursor()
    first_payload = base_payload()
    updated_payload = base_payload()
    updated_payload["customProperties"]["FISCAL_ID"] = "99999"
    updated_payload["saleLines"].append(
        {
            "partCode": 900000033,
            "name": "Produto atualizado",
            "itemType": "PRODUCT",
            "itemId": "1.10021",
            "qty": 3,
            "multipliedQty": 6,
            "itemPrice": 9.5,
            "tags": ["PLUFamilyGroup=COOKIE"],
            "customProperties": {"saleType": "EAT_IN"},
        }
    )
    updated_payload["tenders"].append(
        {"tenderDesc": "Dinheiro", "tenderAmount": 10}
    )

    first = map_order_picture(first_payload, TZ)
    updated = map_order_picture(updated_payload, TZ)

    assert first.venda["loja"] == updated.venda["loja"]
    assert first.venda["data_movimento"] == updated.venda["data_movimento"]
    assert first.venda["numero_pedido"] == updated.venda["numero_pedido"]

    first_result = save_mapped_order(cursor, first)
    updated_result = save_mapped_order(cursor, updated)

    assert first_result.venda_id == updated_result.venda_id == 10
    assert first_result.venda_inserted is True
    assert updated_result.venda_inserted is False
    assert updated_result.pagamentos_removed == 1
    assert updated_result.pagamentos_inserted == 2
    assert updated_result.produtos_removed == 1
    assert updated_result.produtos_inserted == 2

    command_sql = [sql for sql, _ in cursor.commands]
    second_upsert_index = _nth_index(command_sql, "INSERT INTO dw.vendas", 2)
    second_delete_pagamentos_index = _nth_index(command_sql, "DELETE FROM dw.pagamentos", 2)
    second_delete_produtos_index = _nth_index(command_sql, "DELETE FROM dw.produtos", 2)
    second_insert_pagamento_index = _nth_index(command_sql, "INSERT INTO dw.pagamentos", 2)
    second_insert_produto_index = _nth_index(command_sql, "INSERT INTO dw.produtos", 2)

    assert "ON CONFLICT (loja, data_movimento, numero_pedido)" in " ".join(
        UPSERT_VENDA_SQL.split()
    )
    assert "data_negocio" in " ".join(UPSERT_VENDA_SQL.split())
    assert second_upsert_index < second_delete_pagamentos_index
    assert second_delete_pagamentos_index < second_insert_pagamento_index
    assert second_upsert_index < second_delete_produtos_index
    assert second_delete_produtos_index < second_insert_produto_index

    produto_inserts = _matching_commands(cursor.commands, "INSERT INTO dw.produtos")
    pagamento_inserts = _matching_commands(cursor.commands, "INSERT INTO dw.pagamentos")
    assert "business_date" in produto_inserts[0][0]
    assert "business_date" in pagamento_inserts[0][0]
    assert str(produto_inserts[0][1]["business_date"]) == "2026-05-14"
    assert str(pagamento_inserts[0][1]["business_date"]) == "2026-05-14"
    assert "quantidade" in produto_inserts[0][0]
    assert produto_inserts[0][1]["quantidade"] == Decimal("4")
    assert produto_inserts[0][1]["preco_item"] == Decimal("14.9")
    assert produto_inserts[-1][1]["quantidade"] == Decimal("6")
    assert produto_inserts[-1][1]["preco_item"] == Decimal("9.5")


def test_save_mapped_order_cancelamento_remove_venda_e_filhos_e_mantem_so_cancelamento():
    cursor = FakeCursor()
    first_payload = base_payload()
    cancel_payload = base_payload()
    cancel_payload["customProperties"]["VOID_TYPE"] = "VOID_PAID_ORDER"
    cancel_payload["fiscalXmlCancel"] = "<xml />"

    first = map_order_picture(first_payload, TZ)
    cancel = map_order_picture(cancel_payload, TZ)

    first_result = save_mapped_order(cursor, first)
    cancel_result = save_mapped_order(cursor, cancel)

    assert first_result.produtos_inserted == 1
    assert cancel_result.venda_removed is True
    assert cancel_result.pagamentos_removed == 1
    assert cancel_result.pagamentos_inserted == 0
    assert cancel_result.produtos_removed == 1
    assert cancel_result.produtos_inserted == 0
    assert cancel_result.cancelamentos_inserted == 1

    command_sql = [sql for sql, _ in cursor.commands]
    assert _count_matching(command_sql, "INSERT INTO dw.produtos") == 1
    delete_produtos_index = _nth_index(command_sql, "DELETE FROM dw.produtos", 2)
    delete_venda_index = _nth_index(command_sql, "DELETE FROM dw.vendas", 1)
    insert_cancelamento_index = _nth_index(command_sql, "INSERT INTO dw.cancelamentos", 1)
    assert delete_produtos_index < delete_venda_index < insert_cancelamento_index
    cancelamento_insert = _matching_commands(
        cursor.commands, "INSERT INTO dw.cancelamentos"
    )[0]
    assert "business_date" in cancelamento_insert[0]
    assert str(cancelamento_insert[1]["business_date"]) == "2026-05-14"


def test_save_cancelamento_sem_venda_anterior_insere_somente_cancelamento():
    cursor = FakeCursor()
    cancel_payload = base_payload()
    cancel_payload["stateId"] = 4
    cancel = map_order_picture(cancel_payload, TZ)

    result = save_mapped_order(cursor, cancel)

    assert result.venda_id is None
    assert result.venda_inserted is False
    assert result.venda_removed is False
    assert result.pagamentos_inserted == 0
    assert result.produtos_inserted == 0
    assert result.cancelamentos_inserted == 1

    command_sql = [sql for sql, _ in cursor.commands]
    assert _count_matching(command_sql, "INSERT INTO dw.vendas") == 0
    assert _count_matching(command_sql, "INSERT INTO dw.cancelamentos") == 1


def _count_commands(commands, sql):
    return sum(1 for command_sql, _ in commands if command_sql == sql)


def _count_matching(commands, pattern):
    return sum(1 for command_sql in commands if pattern in command_sql)


def _matching_commands(commands, pattern):
    return [
        (command_sql, params)
        for command_sql, params in commands
        if pattern in command_sql
    ]


def _nth_index(commands, pattern, occurrence):
    found = 0
    for index, command_sql in enumerate(commands):
        if pattern in command_sql:
            found += 1
            if found == occurrence:
                return index
    raise AssertionError(f"Comando nao encontrado: {pattern} #{occurrence}")

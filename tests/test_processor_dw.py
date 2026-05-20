from src.mappers import map_order_picture
from src.processor_dw import UPSERT_VENDA_SQL, save_mapped_order
from tests.test_mappers import TZ, base_payload


class FakeCursor:
    def __init__(self):
        self.commands = []
        self.fetchone_rows = []
        self.rowcount = -1

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
            return

        if normalized.startswith("DELETE FROM dw.pagamentos"):
            self.rowcount = 0 if _count_commands(self.commands, normalized) == 1 else 1
            return

        if normalized.startswith("DELETE FROM dw.produtos"):
            self.rowcount = 0 if _count_commands(self.commands, normalized) == 1 else 1
            return

        if normalized.startswith("DELETE FROM dw.cancelamentos"):
            self.rowcount = 0

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
    assert second_upsert_index < second_delete_pagamentos_index
    assert second_delete_pagamentos_index < second_insert_pagamento_index
    assert second_upsert_index < second_delete_produtos_index
    assert second_delete_produtos_index < second_insert_produto_index


def _count_commands(commands, sql):
    return sum(1 for command_sql, _ in commands if command_sql == sql)


def _nth_index(commands, pattern, occurrence):
    found = 0
    for index, command_sql in enumerate(commands):
        if pattern in command_sql:
            found += 1
            if found == occurrence:
                return index
    raise AssertionError(f"Comando nao encontrado: {pattern} #{occurrence}")

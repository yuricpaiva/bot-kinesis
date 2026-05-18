from datetime import datetime
from decimal import Decimal

from src.mappers import map_order_picture
from src.utils import extract_family, to_business_naive


TZ = "America/Fortaleza"


def base_payload():
    return {
        "objectType": "order_picture",
        "storeCode": "0001",
        "orderCode": 10609,
        "businessDt": "2026-05-14",
        "creationDttm": "2026-05-14T00:30:00+00:00",
        "posUser": {"name": "Operador"},
        "totalTender": 99.99,
        "totalAmount": 24.43,
        "discountAmount": 1.5,
        "customProperties": {"FISCAL_ID": "12345", "POS_TYPE": "FC"},
        "benefitData": [{"code": "A"}, {"code": "B"}],
        "tenders": [{"tenderDesc": "TEF Credito", "tenderAmount": 24.43}],
        "saleLines": [
            {
                "partCode": 900000022,
                "name": "Produto teste",
                "itemType": "PRODUCT",
                "itemId": "1.10020",
                "tags": ["PLUFamilyGroup=BROWNIE"],
                "customProperties": {"saleType": "EAT_IN"},
            }
        ],
    }


def test_venda_normal_gera_venda_pagamentos_e_produtos():
    mapped = map_order_picture(base_payload(), TZ)

    assert mapped.skip_dw is False
    assert mapped.venda["loja"] == "0001"
    assert str(mapped.venda["data_movimento"]) == "2026-05-13"
    assert mapped.venda["numero_cupom"] == "12345"
    assert mapped.venda["numero_pedido"] == "10609"
    assert mapped.venda["tipo_venda"] == "EAT_IN"
    assert mapped.venda["tipo_pdv"] == "FC"
    assert mapped.venda["atendente"] == "Operador"
    assert mapped.venda["total_venda"] == Decimal("24.43")
    assert mapped.venda["desconto"] == Decimal("1.5")
    assert mapped.venda["codigo_desconto"] == "A,B"
    assert mapped.venda["cancelado"] is False
    assert len(mapped.pagamentos) == 1
    assert len(mapped.produtos) == 1
    assert mapped.produtos[0]["familia_item"] == "BROWNIE"


def test_void_current_order_ignora_dw():
    payload = base_payload()
    payload["customProperties"]["VOID_TYPE"] = "VOID_CURRENT_ORDER"

    mapped = map_order_picture(payload, TZ)

    assert mapped.skip_dw is True
    assert mapped.skip_reason == "VOID_CURRENT_ORDER"
    assert mapped.venda is None
    assert mapped.pagamentos == []
    assert mapped.produtos == []
    assert mapped.cancelamento is None


def test_void_paid_order_com_fiscal_cancel_marca_cancelado():
    payload = base_payload()
    payload["customProperties"]["VOID_TYPE"] = "VOID_PAID_ORDER"
    payload["fiscalXmlCancel"] = "<xml />"

    mapped = map_order_picture(payload, TZ)

    assert mapped.skip_dw is False
    assert mapped.venda["cancelado"] is True
    assert mapped.cancelamento is not None
    assert mapped.cancelamento["numero_cupom"] == "12345"


def test_sem_fiscal_id_cria_venda_pela_chave_operacional():
    payload = base_payload()
    payload["customProperties"].pop("FISCAL_ID")

    mapped = map_order_picture(payload, TZ)

    assert mapped.skip_dw is False
    assert mapped.venda["numero_cupom"] is None
    assert mapped.venda["loja"] == "0001"
    assert str(mapped.venda["data_movimento"]) == "2026-05-13"
    assert mapped.venda["numero_pedido"] == "10609"


def test_sem_business_dt_nao_impede_chave_operacional():
    payload = base_payload()
    payload.pop("businessDt")

    mapped = map_order_picture(payload, TZ)

    assert mapped.skip_dw is False
    assert str(mapped.venda["data_movimento"]) == "2026-05-13"


def test_sem_creation_dttm_ignora_por_chave_incompleta():
    payload = base_payload()
    payload.pop("creationDttm")

    mapped = map_order_picture(payload, TZ)

    assert mapped.skip_dw is True
    assert mapped.skip_reason == "CHAVE_VENDA_INCOMPLETA"


def test_timezone_fortaleza_altera_dia():
    converted = to_business_naive("2026-05-14T00:30:00+00:00", TZ)

    assert converted == datetime(2026, 5, 13, 21, 30)


def test_extract_family_pega_plu_family_group():
    assert extract_family(["x", "PLUFamilyGroup=COOKIE"]) == "COOKIE"

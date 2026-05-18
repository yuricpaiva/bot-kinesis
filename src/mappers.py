from dataclasses import dataclass
from typing import Any

from .utils import (
    custom_properties,
    extract_family,
    first_sale_type,
    has_value,
    join_benefit_codes,
    to_business_naive,
    to_decimal,
    to_text,
    xml_vnf,
)


@dataclass(frozen=True)
class MappedOrder:
    skip_dw: bool
    skip_reason: str | None
    venda: dict[str, Any] | None
    pagamentos: list[dict[str, Any]]
    produtos: list[dict[str, Any]]
    cancelamento: dict[str, Any] | None


def map_order_picture(payload: dict[str, Any], timezone_name: str) -> MappedOrder:
    props = custom_properties(payload)
    void_type = props.get("VOID_TYPE")
    if void_type == "VOID_CURRENT_ORDER":
        return MappedOrder(True, "VOID_CURRENT_ORDER", None, [], [], None)

    fiscal_id = to_text(props.get("FISCAL_ID"))
    sale_lines = payload.get("saleLines")
    tenders = payload.get("tenders")
    data_hora = to_business_naive(payload.get("creationDttm"), timezone_name)
    data_movimento = data_hora.date() if data_hora is not None else None
    loja = to_text(payload.get("storeCode"))
    numero_pedido = to_text(payload.get("orderCode"))
    if not loja or data_movimento is None or not numero_pedido:
        return MappedOrder(True, "CHAVE_VENDA_INCOMPLETA", None, [], [], None)

    tipo_venda = first_sale_type(sale_lines)
    tipo_pdv = to_text(props.get("POS_TYPE"))
    atendente = _attendant_name(payload.get("posUser"))
    fiscal_cancel = has_value(payload.get("fiscalXmlCancel"))

    venda = {
        "loja": loja,
        "data_hora": data_hora,
        "data_movimento": data_movimento,
        "numero_cupom": fiscal_id,
        "numero_pedido": numero_pedido,
        "tipo_venda": tipo_venda,
        "tipo_pdv": tipo_pdv,
        "atendente": atendente,
        "total_venda": _total_venda_from_xml(payload),
        "desconto": to_decimal(payload.get("discountAmount")),
        "codigo_desconto": join_benefit_codes(payload.get("benefitData")),
        "cancelado": fiscal_cancel,
    }

    pagamentos = _map_pagamentos(tenders, venda)
    produtos = _map_produtos(sale_lines, venda, tipo_pdv)
    cancelamento = _map_cancelamento(venda) if fiscal_cancel else None
    return MappedOrder(False, None, venda, pagamentos, produtos, cancelamento)


def _map_pagamentos(tenders: Any, venda: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(tenders, list):
        return []
    rows = []
    for tender in tenders:
        if not isinstance(tender, dict):
            continue
        rows.append(
            {
                "loja": venda["loja"],
                "data_hora": venda["data_hora"],
                "numero_cupom": venda["numero_cupom"],
                "numero_pedido": venda["numero_pedido"],
                "forma_pagamento": to_text(tender.get("tenderDesc")),
                "valor_pagamento": to_decimal(tender.get("tenderAmount")),
            }
        )
    return rows


def _map_produtos(
    sale_lines: Any,
    venda: dict[str, Any],
    tipo_pdv: str | None,
) -> list[dict[str, Any]]:
    if not isinstance(sale_lines, list):
        return []
    rows = []
    for line in sale_lines:
        if not isinstance(line, dict):
            continue
        props = line.get("customProperties")
        line_sale_type = (
            to_text(props.get("saleType")) if isinstance(props, dict) else None
        )
        rows.append(
            {
                "loja": venda["loja"],
                "data_hora": venda["data_hora"],
                "numero_cupom": venda["numero_cupom"],
                "numero_pedido": venda["numero_pedido"],
                "tipo_venda": line_sale_type,
                "tipo_pdv": tipo_pdv,
                "codigo_produto": to_text(line.get("partCode")),
                "descricao_produto": to_text(line.get("name")),
                "item_type": to_text(line.get("itemType")),
                "item_id": to_text(line.get("itemId")),
                "familia_item": extract_family(line.get("tags")),
            }
        )
    return rows


def _map_cancelamento(venda: dict[str, Any]) -> dict[str, Any]:
    return {
        "loja": venda["loja"],
        "data_hora": venda["data_hora"],
        "numero_cupom": venda["numero_cupom"],
        "numero_pedido": venda["numero_pedido"],
        "tipo_venda": venda["tipo_venda"],
        "tipo_pdv": venda["tipo_pdv"],
        "atendente": venda["atendente"],
        "total_venda": venda["total_venda"],
    }


def _total_venda_from_xml(payload: dict[str, Any]) -> Any:
    for field_name in (
        "fiscalXml",
        "fiscalXmlNfe",
        "fiscalXmlCancel",
        "fiscalXmlNfeCancel",
    ):
        value = xml_vnf(payload.get(field_name))
        if value is not None:
            return value
    return None


def _attendant_name(pos_user: Any) -> str | None:
    if isinstance(pos_user, dict):
        return to_text(pos_user.get("name"))
    return to_text(pos_user)

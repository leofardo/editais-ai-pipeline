"""Contrato da extração: o que o LLM DEVE devolver para cada edital.

Usado como *structured output* da OpenAI: o modelo é obrigado a seguir este
schema, e o Pydantic valida tipos antes de qualquer dado chegar à silver.
Campos sem informação no texto devem vir como null (nunca inventados).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Cargo(BaseModel):
    nome: str = Field(description="Nome do cargo/função exatamente como no edital")
    area: Optional[str] = Field(description="Área de atuação resumida: TI, saúde, educação, administrativa, segurança, jurídica, engenharia, outra")
    escolaridade: Literal["fundamental", "medio", "tecnico", "superior", "nao_informado"]
    vagas_ampla_concorrencia: Optional[int] = Field(description="Vagas imediatas de ampla concorrência")
    vagas_total: Optional[int] = Field(description="Número de vagas da linha deste cargo no quadro geral, copiado sem fazer contas")
    vagas_referem_se_ao_grupo: bool = Field(description=(
        "True se o número em vagas_total NÃO é específico deste cargo, e sim o total de uma carreira/grupo "
        "que contém vários cargos ou especialidades (ex.: '10.170 vagas para os cargos da carreira de Professor'). "
        "False se o número é exclusivo deste cargo."))
    cadastro_reserva: bool = Field(description="True se o cargo tiver cadastro reserva (CR)")
    salario_inicial: Optional[float] = Field(description="Remuneração/vencimento inicial MENSAL em reais (ex.: 8500.00)")
    carga_horaria_semanal: Optional[int]
    localidade: Optional[str] = Field(description="Cidade/lotação, se o edital especificar")
    requisitos: Optional[str] = Field(description="Requisitos de formação, resumidos em até 200 caracteres")
    pagina_fonte: Optional[int] = Field(description="Número da página (marcador '=== Página N ===') onde o cargo aparece")


class Edital(BaseModel):
    orgao: str = Field(description="Órgão/instituição que abre o concurso")
    numero_edital: Optional[str]
    banca_organizadora: Optional[str]
    esfera: Literal["municipal", "estadual", "federal", "nao_informado"]
    uf: Optional[str] = Field(description="Sigla da UF com 2 letras")
    municipio: Optional[str]
    data_publicacao: Optional[str] = Field(description="YYYY-MM-DD")
    inscricao_inicio: Optional[str] = Field(description="YYYY-MM-DD")
    inscricao_fim: Optional[str] = Field(description="YYYY-MM-DD")
    data_prova: Optional[str] = Field(description="YYYY-MM-DD da prova objetiva")
    taxa_inscricao_min: Optional[float]
    taxa_inscricao_max: Optional[float]
    documento_completo: bool = Field(description="False se o texto for só anexos, retificação ou trecho parcial do edital")
    cargos: list[Cargo]
    observacoes: Optional[str] = Field(description="Ambiguidades ou dados faltantes relevantes, em até 300 caracteres")

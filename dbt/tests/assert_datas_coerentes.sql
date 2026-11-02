-- Inscrição deve terminar depois de começar, e a prova não pode ser antes do início das inscrições.
select edital_id, inscricao_inicio, inscricao_fim, data_prova
from {{ ref('dim_editais') }}
where (inscricao_inicio > inscricao_fim)
   or (data_prova < inscricao_inicio)

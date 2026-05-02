# Visitor

## Probleme
On veut appliquer des operations variees (indexation RAG, export, validation) sur une structure d'objets sans modifier leurs classes. Ajouter chaque operation dans les classes viole le principe ouvert/ferme.

## Solution
Definir un visiteur externe qui parcourt la structure et applique une operation a chaque element. Les elements acceptent le visiteur via une methode `accept()`.

## Exemple
```python
from abc import ABC, abstractmethod

class DeliverableVisitor(ABC):
    @abstractmethod
    async def visit_document(self, doc: "DocumentDeliverable"): ...
    @abstractmethod
    async def visit_code(self, code: "CodeDeliverable"): ...

class RAGIndexVisitor(DeliverableVisitor):
    """Indexe les livrables dans pgvector pour le RAG."""
    def __init__(self, embedding_service):
        self.embedder = embedding_service
    async def visit_document(self, doc):
        chunks = split_text(doc.content, chunk_size=512)
        embeddings = await self.embedder.embed_batch(chunks)
        await pgvector_upsert(doc.id, chunks, embeddings)
    async def visit_code(self, code):
        chunks = split_by_function(code.source)
        embeddings = await self.embedder.embed_batch(chunks)
        await pgvector_upsert(code.id, chunks, embeddings)

# Parcourir tous les livrables d'une phase
indexer = RAGIndexVisitor(voyage_ai_service)
for deliverable in phase.deliverables:
    await deliverable.accept(indexer)
```

## Quand l'utiliser
- Plusieurs operations distinctes sur la meme structure (RAG indexation, export PDF, validation)
- La structure est stable mais les operations evoluent frequemment
- On veut separer la logique de traversal de la logique metier
- Les operations dependent du type concret de l'element

## Quand ne PAS l'utiliser
- La structure change souvent (ajouter un type = modifier tous les visiteurs)
- Une seule operation a appliquer (une boucle simple suffit)
- Les elements n'ont pas de types distincts significatifs

# Legal Domain Schema

## Entity Types

```yaml
statute:
  description: "Law or regulation"
  properties:
    - name
    - jurisdiction: string
    - code: string  # e.g., "15 U.S.C. § 45"
    - effective_date: date
    - keywords: [string]
    - summary: string

clause:
  description: "Section or paragraph within a legal document"
  properties:
    - number: string
    - title: string
    - content: text
    - parent_document: contract_id | statute_id
    - obligation_type: [rights, duties, prohibitions, permissions]
    - parties: [party_id]

case:
  description: "Court case or legal precedent"
  properties:
    - citation: string
    - court: string
    - date: date
    - judge: string
    - parties: [party_id]
    - holding: text
    - reasoning: text
    - cited_statutes: [statute_id]
    - cited_cases: [case_id]

party:
  description: "Legal entity (person or organization)"
  properties:
    - name
    - type: [individual, corporation, government, nonprofit]
    - role: [plaintiff, defendant, petitioner, respondent, intervenor]
    - jurisdiction: string
    - counsel: string

obligation:
  description: "Legal duty or requirement"
  properties:
    - description: text
    - source: clause_id | statute_id
    - obligated_party: party_id
    - beneficiary: party_id
    - deadline: date
    - penalty: string

deadline:
  description: "Legal time limit or deadline"
  properties:
    - date
    - type: [filing, response, payment, hearing]
    - related_case: case_id
    - related_contract: contract_id
    - consequence: string

contract:
  description: "Legal agreement or contract"
  properties:
    - title
    - parties: [party_id]
    - effective_date: date
    - expiration_date: date
    - type: [nda, employment, lease, service, sale]
    - clauses: [clause_id]
    - jurisdiction: string
    - status: [active, expired, terminated, disputed]
```

## Relationship Types

```yaml
clause.derived_from: statute
clause.引用: statute  # references
clause.creates: obligation

case.applies: statute
case.cites: case
case.involves: party

obligation.arises_from: clause | statute
obligation.benefits: party

deadline.for_case: case
deadline.for_contract: contract

contract.between: party
contract.contains: clause
contract.amended_by: contract

party.represented_by: party  # counsel
party.against: party  # litigation
```

## Extraction Rules

1. **PDF documents**: OCR + rule-based extraction
2. **Court opinions**: Structured case citation parsing
3. **Contracts**: Clause segmentation and obligation tagging
4. **Regulations**: Code section parsing (e.g., "15 U.S.C. § 45")
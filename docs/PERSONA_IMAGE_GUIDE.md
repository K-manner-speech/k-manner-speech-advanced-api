# K-Manner Speech 페르소나 이미지 제작 가이드

> 상태: MVP 1.0 기준 초안  
> 대상: 기획자, 디자이너, 이미지 생성 담당자, 프론트엔드 개발자  
> 목적: 동일한 AI 페르소나가 감정에 따라 표정만 자연스럽게 바뀌도록 제작·검수·관리한다.

## 1. 기본 원칙

- 페르소나는 실제 인물 사진과 유사한 자연스러운 AI 생성 이미지로 제작한다.
- MVP에서는 실시간 이미지 생성 대신 검수된 감정별 이미지를 사전에 준비한다.
- 각 페르소나는 `neutral`, `happy`, `sad`, `angry` 네 장을 기본 세트로 갖는다.
- 감정이 바뀌어도 동일 인물로 즉시 인식할 수 있어야 한다.
- 표정은 학습 맥락을 돕는 수준으로 표현하며 과장하거나 위협적으로 만들지 않는다.
- 실제 인물이나 유명인을 모방하지 않고, 권리와 동의가 확인되지 않은 참조 사진을 사용하지 않는다.

## 2. 페르소나 정의서

이미지를 생성하기 전에 페르소나마다 다음 정보를 확정한다.

| 항목 | 작성 내용 |
| --- | --- |
| `persona_id` | 영문 소문자와 하이픈으로 된 고유 ID |
| 이름 | 서비스에서 표시할 가상 인물명 |
| 역할 | 면접관, 직장 동료, 친구 등 |
| 관계 | 사용자와의 관계 및 권력·친밀도 |
| 나이대 | 구체적인 나이보다 범위로 정의 |
| 외형 특징 | 머리, 얼굴형, 안경 등 식별 특징 |
| 의상 | 역할과 상황에 맞는 고정 의상 |
| 배경 | 고정된 장소와 색상 톤 |
| 카메라 | 구도, 거리, 렌즈 느낌, 시선 |
| 조명 | 방향, 밝기, 색온도 |
| 금지 요소 | 바뀌거나 추가되면 안 되는 요소 |

예시:

```yaml
persona_id: interviewer-seojun
name: 김서준
role: IT 기업 팀장 면접관
relationship: 처음 만난 지원자를 평가하는 공식적 관계
age_range: 30대 후반
appearance: 짧은 검은 머리, 둥근 얼굴, 얇은 금속 안경
wardrobe: 네이비 재킷, 흰색 셔츠
background: 밝고 단정한 회의실, 흐린 배경
camera: 정면 시선, 상반신, eye-level, 4:5
lighting: 부드러운 자연광, 중성 색온도
do_not_change: 얼굴, 머리, 안경, 의상, 배경, 구도, 조명
```

## 3. 이미지 사양

| 항목 | 기준 |
| --- | --- |
| 원본 비율 | `4:5` |
| 최소 원본 크기 | `1024×1280px` |
| 색공간 | sRGB |
| 원본 보관 | 고품질 PNG 또는 생성 도구 원본 |
| 서비스 제공 | WebP 우선, AVIF 선택 지원 |
| 안전 영역 | 얼굴과 핵심 표정이 중앙 70% 안에 위치 |
| 배경 | 감정별로 동일하거나 육안상 차이가 없어야 함 |

파생 이미지 권장 크기:

- 대화 화면: `640×800px`
- 모바일 대화 화면: `480×600px`
- 목록·선택 카드: `240×300px`
- 작은 아바타는 별도 정사각형 크롭을 사용하되 원본을 덮어쓰지 않는다.

## 4. 감정별 표현 기준

### 4.1 Neutral

- 편안하고 주의 깊은 기본 표정
- 입은 자연스럽게 닫거나 아주 약한 미소
- 눈썹과 어깨에 긴장이 없어야 함
- 감정 분석 전, 불확실, 실패 상태의 기본 이미지로 사용

### 4.2 Happy

- 눈과 입에서 자연스러운 미소가 함께 보여야 함
- 치아 노출은 선택 사항이며 과도한 웃음은 피함
- 머리, 의상과 몸의 방향은 neutral과 동일하게 유지

### 4.3 Sad

- 눈빛과 입꼬리가 조금 내려간 차분한 슬픔
- 울음, 눈물, 극단적인 절망 표현은 사용하지 않음
- 사용자가 죄책감이나 공포를 느낄 정도로 과장하지 않음

### 4.4 Angry

- 불편함 또는 단호함을 보여주는 표정
- 눈썹과 입 주변의 긴장으로 표현
- 고함, 위협, 주먹, 공격 자세, 심하게 붉어진 얼굴은 금지
- 학습자가 상대 반응을 이해하는 데 필요한 수준으로 제한

## 5. 제작 흐름

1. 페르소나 정의서를 승인한다.
2. `neutral` 기준 이미지를 여러 장 생성한다.
3. 얼굴 일관성, 역할 적합성, 편향과 안전성을 검수해 기준 이미지를 한 장 선택한다.
4. 기준 이미지를 참조 이미지로 사용해 `happy`, `sad`, `angry`를 생성한다.
5. 네 장을 동시에 비교해 인물·구도·의상·배경 일관성을 검수한다.
6. 필요한 이미지만 다시 생성하거나 편집한다.
7. 최종 원본과 서비스용 파생 이미지를 저장한다.
8. 매니페스트에 경로, 버전과 검수 상태를 기록한다.

감정별 이미지를 서로 독립적인 텍스트 프롬프트로 처음부터 생성하지 않는다. 가능한 경우 기준 이미지, 고정 시드, 캐릭터 참조 또는 이미지 편집 기능을 사용한다.

## 6. 프롬프트 구조

프롬프트는 `고정 인물 정보 + 고정 촬영 조건 + 변경할 감정 + 금지 조건` 순서로 구성한다.

### 6.1 기준 이미지 프롬프트 예시

```text
Photorealistic portrait of a fictional Korean male team leader in his late 30s,
short black hair, round face, thin metal glasses, navy jacket and white shirt.
Upper-body portrait, eye-level camera, looking toward the camera, bright tidy
meeting room with softly blurred background, soft natural lighting, neutral
color temperature, realistic skin texture, calm and attentive neutral expression,
consistent 4:5 composition. This must be a fictional person and must not resemble
any celebrity or real public figure.
```

### 6.2 감정 변형 지시 예시

```text
Keep the exact same fictional person, facial identity, hair, glasses, clothing,
camera angle, crop, lighting and background. Change only the facial expression to
a natural, restrained happy expression with a gentle smile. Do not change age,
body position, accessories or environment.
```

감정별 마지막 구절만 다음처럼 교체한다.

- `happy`: 자연스럽고 절제된 미소
- `sad`: 차분하고 약한 슬픔, 눈물 없음
- `angry`: 위협적이지 않은 불편함과 단호함

### 6.3 네거티브 지시

```text
different person, changed face, changed hairstyle, changed clothes, changed
background, different camera angle, different crop, exaggerated emotion, shouting,
crying, aggressive pose, distorted eyes, asymmetrical face, extra limbs, text,
logo, watermark, celebrity likeness, overly retouched skin, cartoon, illustration
```

사용하는 생성 도구가 별도의 네거티브 프롬프트를 지원하지 않으면 동일 내용을 일반 프롬프트의 금지 조건으로 포함한다.

## 7. 파일 구조와 명명

```text
assets/personas/
  interviewer-seojun/
    source/
      neutral.png
      happy.png
      sad.png
      angry.png
    web/
      neutral.webp
      happy.webp
      sad.webp
      angry.webp
    thumbnail/
      neutral.webp
      happy.webp
      sad.webp
      angry.webp
    persona.json
```

- 폴더와 파일명은 영문 소문자, 숫자, 하이픈만 사용한다.
- 감정 상태 키는 `neutral`, `happy`, `sad`, `angry`로 고정한다.
- 재생성으로 기존 이미지가 바뀌면 매니페스트의 버전을 올린다.
- 이전 버전이 이미 배포된 경우 덮어쓰기보다 버전 경로 또는 캐시 무효화 정책을 사용한다.

## 8. 매니페스트 예시

```json
{
  "persona_id": "interviewer-seojun",
  "version": 1,
  "display_name": "김서준 팀장",
  "role": "interviewer",
  "aspect_ratio": "4:5",
  "images": {
    "neutral": "/assets/personas/interviewer-seojun/web/neutral.webp",
    "happy": "/assets/personas/interviewer-seojun/web/happy.webp",
    "sad": "/assets/personas/interviewer-seojun/web/sad.webp",
    "angry": "/assets/personas/interviewer-seojun/web/angry.webp"
  },
  "fallback": "neutral",
  "review_status": "approved"
}
```

## 9. 감정값 매핑

Gemini의 원본 응답은 공용 매퍼에서 다음 네 상태 중 하나로 정규화한다.

| 모델 감정 예시 | 이미지 상태 |
| --- | --- |
| 기쁨, 즐거움, 만족 | `happy` |
| 슬픔, 실망 | `sad` |
| 화남, 불쾌함, 짜증 | `angry` |
| 보통, 궁금, 당황, 불확실 | `neutral` |
| 누락, 알 수 없음, 분석 실패 | `neutral` |

```ts
type PersonaEmotion = "neutral" | "happy" | "sad" | "angry";
```

- 모델 문자열을 이미지 경로에 직접 결합하지 않는다.
- 허용 목록에 없는 값은 항상 `neutral`로 처리한다.
- 같은 정규화 결과를 페르소나 이미지와 TTS 감정 스타일에 사용한다.

## 10. 화면 동작

- 대화 시작 전에 `neutral`을 표시한다.
- AI 대화 응답의 감정이 확정되면 해당 이미지를 미리 불러온 뒤 전환한다.
- `200–320ms` 페이드로 교체하며 레이아웃 크기는 고정한다.
- 한 AI 메시지 중에는 표정을 한 번만 확정하고 반복 변경하지 않는다.
- 이미지가 없거나 로딩에 실패하면 `neutral`로 복귀한다.
- 모든 이미지가 실패하면 실루엣, 페르소나 이름과 감정 라벨을 표시한다.
- 이미지 대체 텍스트에는 인물 역할과 표정을 포함한다. 예: `면접관 김서준이 부드럽게 미소 짓는 모습`.

## 11. QA 체크리스트

### 인물 일관성

- [ ] 네 이미지가 같은 인물로 즉시 인식된다.
- [ ] 얼굴형, 눈, 코, 입과 피부색이 유지된다.
- [ ] 나이대와 성별 표현이 갑자기 바뀌지 않는다.
- [ ] 머리, 안경, 의상과 액세서리가 동일하다.
- [ ] 배경, 조명, 카메라 각도와 크롭이 동일하다.

### 감정과 품질

- [ ] 네 감정의 차이를 색상 없이 표정으로 구분할 수 있다.
- [ ] 감정이 과장되거나 위협적이지 않다.
- [ ] 얼굴, 손, 치아, 안경 등에 생성 오류가 없다.
- [ ] 이미지에 글자, 로고, 워터마크가 없다.
- [ ] 작은 모바일 화면에서도 표정이 식별된다.

### 안전과 공정성

- [ ] 유명인 또는 특정 실제 인물과 유사하지 않다.
- [ ] 역할, 나이, 성별, 국적에 대한 불필요한 고정관념을 강화하지 않는다.
- [ ] 외모를 능력, 성격 또는 신뢰성과 연결하지 않는다.
- [ ] 사용 권한이 불명확한 참조 이미지를 사용하지 않았다.
- [ ] AI 생성 이미지임을 알리는 제품 정책이 적용되어 있다.

### 기술 검수

- [ ] 모든 파일 경로와 매니페스트가 일치한다.
- [ ] WebP/AVIF가 목표 브라우저와 앱에서 표시된다.
- [ ] 이미지 용량과 로딩 시간이 허용 범위 안이다.
- [ ] 다음 상태 이미지가 사전 로드된다.
- [ ] 로딩 실패 시 `neutral`과 최종 대체 UI가 정상 작동한다.
- [ ] 이미지와 TTS가 같은 감정 상태를 사용한다.

## 12. 승인과 변경 관리

- 페르소나 정의서와 `neutral` 기준 이미지는 감정 변형 전에 승인한다.
- 네 장의 이미지 세트는 낱장이 아닌 한 화면에서 비교해 승인한다.
- 얼굴 또는 의상 변경은 새 감정 이미지가 아니라 페르소나 새 버전으로 취급한다.
- 승인된 원본, 생성 설정, 참조 이미지와 검수 기록을 함께 보관한다.
- 생성 도구나 모델을 변경하면 기존 세트와 시각적 일관성을 다시 검수한다.
- 디자인 시스템의 페르소나 규칙이 변경되면 이 문서와 구현 매핑도 함께 갱신한다.

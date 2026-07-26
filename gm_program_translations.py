"""Regional General MIDI Level 1 program names in program-number order.

The Chinese source names live in :mod:`bdo_midi.instruments`.  This table is
kept positional so the import boundary can verify all 128 programs without
duplicating program numbers or changing project data after a track is created.
Each row is ``(en_US, ja_JP, ko_KR)``.
"""

from __future__ import annotations


GM_PROGRAM_TRANSLATIONS = (
    # 0-7: Piano
    ("Acoustic Grand Piano", "アコースティックグランドピアノ", "어쿠스틱 그랜드 피아노"),
    ("Bright Acoustic Piano", "ブライトアコースティックピアノ", "브라이트 어쿠스틱 피아노"),
    ("Electric Grand Piano", "エレクトリックグランドピアノ", "일렉트릭 그랜드 피아노"),
    ("Honky-tonk Piano", "ホンキートンクピアノ", "홍키통크 피아노"),
    ("Electric Piano 1", "エレクトリックピアノ1", "일렉트릭 피아노 1"),
    ("Electric Piano 2", "エレクトリックピアノ2", "일렉트릭 피아노 2"),
    ("Harpsichord", "ハープシコード", "하프시코드"),
    ("Clavinet", "クラビネット", "클라비넷"),
    # 8-15: Chromatic percussion
    ("Celesta", "チェレスタ", "첼레스타"),
    ("Glockenspiel", "グロッケンシュピール", "글로켄슈필"),
    ("Music Box", "ミュージックボックス", "뮤직 박스"),
    ("Vibraphone", "ビブラフォン", "비브라폰"),
    ("Marimba", "マリンバ", "마림바"),
    ("Xylophone", "シロフォン", "실로폰"),
    ("Tubular Bells", "チューブラーベル", "튜블러 벨"),
    ("Dulcimer", "ダルシマー", "덜시머"),
    # 16-23: Organ
    ("Drawbar Organ", "ドローバーオルガン", "드로바 오르간"),
    ("Percussive Organ", "パーカッシブオルガン", "퍼커시브 오르간"),
    ("Rock Organ", "ロックオルガン", "록 오르간"),
    ("Church Organ", "チャーチオルガン", "처치 오르간"),
    ("Reed Organ", "リードオルガン", "리드 오르간"),
    ("Accordion", "アコーディオン", "아코디언"),
    ("Harmonica", "ハーモニカ", "하모니카"),
    ("Tango Accordion", "タンゴアコーディオン", "탱고 아코디언"),
    # 24-31: Guitar
    ("Acoustic Guitar (nylon)", "アコースティックギター（ナイロン）", "어쿠스틱 기타(나일론)"),
    ("Acoustic Guitar (steel)", "アコースティックギター（スチール）", "어쿠스틱 기타(스틸)"),
    ("Electric Guitar (jazz)", "エレクトリックギター（ジャズ）", "일렉트릭 기타(재즈)"),
    ("Electric Guitar (clean)", "エレクトリックギター（クリーン）", "일렉트릭 기타(클린)"),
    ("Electric Guitar (muted)", "エレクトリックギター（ミュート）", "일렉트릭 기타(뮤트)"),
    ("Overdriven Guitar", "オーバードライブギター", "오버드라이브 기타"),
    ("Distortion Guitar", "ディストーションギター", "디스토션 기타"),
    ("Guitar Harmonics", "ギターハーモニクス", "기타 하모닉스"),
    # 32-39: Bass
    ("Acoustic Bass", "アコースティックベース", "어쿠스틱 베이스"),
    ("Electric Bass (finger)", "エレクトリックベース（フィンガー）", "일렉트릭 베이스(핑거)"),
    ("Electric Bass (pick)", "エレクトリックベース（ピック）", "일렉트릭 베이스(피크)"),
    ("Fretless Bass", "フレットレスベース", "프렛리스 베이스"),
    ("Slap Bass 1", "スラップベース1", "슬랩 베이스 1"),
    ("Slap Bass 2", "スラップベース2", "슬랩 베이스 2"),
    ("Synth Bass 1", "シンセベース1", "신스 베이스 1"),
    ("Synth Bass 2", "シンセベース2", "신스 베이스 2"),
    # 40-47: Strings
    ("Violin", "バイオリン", "바이올린"),
    ("Viola", "ビオラ", "비올라"),
    ("Cello", "チェロ", "첼로"),
    ("Contrabass", "コントラバス", "콘트라베이스"),
    ("Tremolo Strings", "トレモロストリングス", "트레몰로 스트링"),
    ("Pizzicato Strings", "ピチカートストリングス", "피치카토 스트링"),
    ("Orchestral Harp", "オーケストラハープ", "오케스트라 하프"),
    ("Timpani", "ティンパニ", "팀파니"),
    # 48-55: Ensemble
    ("String Ensemble 1", "ストリングアンサンブル1", "스트링 앙상블 1"),
    ("String Ensemble 2", "ストリングアンサンブル2", "스트링 앙상블 2"),
    ("Synth Strings 1", "シンセストリングス1", "신스 스트링 1"),
    ("Synth Strings 2", "シンセストリングス2", "신스 스트링 2"),
    ("Choir Aahs", "クワイア・アー", "콰이어 아"),
    ("Voice Oohs", "ボイス・ウー", "보이스 우"),
    ("Synth Voice", "シンセボイス", "신스 보이스"),
    ("Orchestra Hit", "オーケストラヒット", "오케스트라 히트"),
    # 56-63: Brass
    ("Trumpet", "トランペット", "트럼펫"),
    ("Trombone", "トロンボーン", "트롬본"),
    ("Tuba", "チューバ", "튜바"),
    ("Muted Trumpet", "ミュートトランペット", "뮤트 트럼펫"),
    ("French Horn", "フレンチホルン", "프렌치 호른"),
    ("Brass Section", "ブラスセクション", "브라스 섹션"),
    ("Synth Brass 1", "シンセブラス1", "신스 브라스 1"),
    ("Synth Brass 2", "シンセブラス2", "신스 브라스 2"),
    # 64-71: Reed
    ("Soprano Sax", "ソプラノサックス", "소프라노 색소폰"),
    ("Alto Sax", "アルトサックス", "알토 색소폰"),
    ("Tenor Sax", "テナーサックス", "테너 색소폰"),
    ("Baritone Sax", "バリトンサックス", "바리톤 색소폰"),
    ("Oboe", "オーボエ", "오보에"),
    ("English Horn", "イングリッシュホルン", "잉글리시 호른"),
    ("Bassoon", "ファゴット", "바순"),
    ("Clarinet", "クラリネット", "클라리넷"),
    # 72-79: Pipe
    ("Piccolo", "ピッコロ", "피콜로"),
    ("Flute", "フルート", "플룻"),
    ("Recorder", "リコーダー", "리코더"),
    ("Pan Flute", "パンフルート", "팬 플루트"),
    ("Blown Bottle", "ボトルブロー", "보틀 블로우"),
    ("Shakuhachi", "尺八", "샤쿠하치"),
    ("Whistle", "ホイッスル", "휘슬"),
    ("Ocarina", "オカリナ", "오카리나"),
    # 80-87: Synth lead
    ("Lead 1 (square)", "リード1（スクエア）", "리드 1(스퀘어)"),
    ("Lead 2 (sawtooth)", "リード2（ソートゥース）", "리드 2(소우투스)"),
    ("Lead 3 (calliope)", "リード3（カリオペ）", "리드 3(칼리오페)"),
    ("Lead 4 (chiff)", "リード4（チフ）", "리드 4(치프)"),
    ("Lead 5 (charang)", "リード5（チャラン）", "리드 5(차랑)"),
    ("Lead 6 (voice)", "リード6（ボイス）", "리드 6(보이스)"),
    ("Lead 7 (fifths)", "リード7（フィフス）", "리드 7(피프스)"),
    ("Lead 8 (bass + lead)", "リード8（ベース＋リード）", "리드 8(베이스+리드)"),
    # 88-95: Synth pad
    ("Pad 1 (new age)", "パッド1（ニューエイジ）", "패드 1(뉴에이지)"),
    ("Pad 2 (warm)", "パッド2（ウォーム）", "패드 2(웜)"),
    ("Pad 3 (polysynth)", "パッド3（ポリシンセ）", "패드 3(폴리신스)"),
    ("Pad 4 (choir)", "パッド4（クワイア）", "패드 4(콰이어)"),
    ("Pad 5 (bowed)", "パッド5（ボウド）", "패드 5(보우드)"),
    ("Pad 6 (metallic)", "パッド6（メタリック）", "패드 6(메탈릭)"),
    ("Pad 7 (halo)", "パッド7（ハロー）", "패드 7(헤일로)"),
    ("Pad 8 (sweep)", "パッド8（スイープ）", "패드 8(스윕)"),
    # 96-103: Synth effects
    ("FX 1 (rain)", "FX 1（レイン）", "FX 1(레인)"),
    ("FX 2 (soundtrack)", "FX 2（サウンドトラック）", "FX 2(사운드트랙)"),
    ("FX 3 (crystal)", "FX 3（クリスタル）", "FX 3(크리스털)"),
    ("FX 4 (atmosphere)", "FX 4（アトモスフィア）", "FX 4(애트모스피어)"),
    ("FX 5 (brightness)", "FX 5（ブライトネス）", "FX 5(브라이트니스)"),
    ("FX 6 (goblins)", "FX 6（ゴブリン）", "FX 6(고블린)"),
    ("FX 7 (echoes)", "FX 7（エコー）", "FX 7(에코)"),
    ("FX 8 (sci-fi)", "FX 8（SF）", "FX 8(SF)"),
    # 104-111: Ethnic
    ("Sitar", "シタール", "시타르"),
    ("Banjo", "バンジョー", "밴조"),
    ("Shamisen", "三味線", "샤미센"),
    ("Koto", "琴", "고토"),
    ("Kalimba", "カリンバ", "칼림바"),
    ("Bag Pipe", "バグパイプ", "백파이프"),
    ("Fiddle", "フィドル", "피들"),
    ("Shanai", "シャナイ", "샤나이"),
    # 112-119: Percussive
    ("Tinkle Bell", "ティンクルベル", "팅클 벨"),
    ("Agogo", "アゴゴ", "아고고"),
    ("Steel Drums", "スチールドラム", "스틸 드럼"),
    ("Woodblock", "ウッドブロック", "우드블록"),
    ("Taiko Drum", "太鼓", "타이코 드럼"),
    ("Melodic Tom", "メロディックタム", "멜로딕 톰"),
    ("Synth Drum", "シンセドラム", "신스 드럼"),
    ("Reverse Cymbal", "リバースシンバル", "리버스 심벌"),
    # 120-127: Sound effects
    ("Guitar Fret Noise", "ギターフレットノイズ", "기타 프렛 노이즈"),
    ("Breath Noise", "ブレスノイズ", "브레스 노이즈"),
    ("Seashore", "海岸", "해변"),
    ("Bird Tweet", "鳥のさえずり", "새소리"),
    ("Telephone Ring", "電話のベル", "전화 벨"),
    ("Helicopter", "ヘリコプター", "헬리콥터"),
    ("Applause", "拍手", "박수"),
    ("Gunshot", "銃声", "총성"),
)


__all__ = ["GM_PROGRAM_TRANSLATIONS"]

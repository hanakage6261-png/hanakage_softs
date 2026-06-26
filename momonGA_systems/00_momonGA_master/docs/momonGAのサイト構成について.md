# このMaekdownについて
これは、このプログラム群が対象とするサイトである、
https://momon-ga.com/
というサイトの特色について説明したものです。

## 対象サイトの構成について

### 対象サイトの作品URLについて

 https://momon-ga.com/
  このサイトでは作品が存在しますが、各作品ページごとに固有のIDが割り振られています。
  （具体例）
  -https://momon-ga.com/fanzine/mo3998769/
  -https://momon-ga.com/magazine/mo4010030/

  このような作品URLが存在しています。
  URLの構成は、
  ①https://momon-ga.com/  
  ②fanzineまたはmagazine
  ③mo(自然数値)
  となっています。
  ③は作品のIDであり、作品ごとに固有の自然数が割り振られています。
  momonGA_systems群ではこのIDを利用して作品の管理やメタデータの収集を行っています。

  また、②の　magazine fanzineについてですが、これは各作品が商業誌または同人誌のどちらかにカテゴライズされており、それを示しているものです。
  
  ただし、ここで注意すべきはこの二つによって別々のID空間が設けられているというわけではないということです。
  具体的に説明しますと、例えば、
  https://momon-ga.com/magazine/mo4010030/
  というURLが存在していますが、
  https://momon-ga.com/fanzine/mo4010030/
  とアドレスバーに入力しても 
  https://momon-ga.com/magazine/mo4010030/
  へとリダイレクトされます。

  このことから、fanzine magazineはID空間を分けるものではなく、単なるラベリングであり、このサイトにおける作品ページはIDによってのみ一意に定まると分かります。
  以上がこのサイトの作品のURLとIDについての説明です。


### ホームページ（https://momon-ga.com/）についての説明

サイトホームページには以下のカテゴリーがあり、おすすめ作品が並べられています。
定期的に更新されます。

- 同人誌(fanzine)
 https://momon-ga.com/fanzine/
 （補足）
 fanzineがURLについた作品全てを含む集合を指すURL

- 商業誌(magazine)
 https://momon-ga.com/magazine/
 （補足）
 magazineがURLについた作品全てを指すURL

- 急上昇(トレンド)
 https://momon-ga.com/trend/

- 人気(ランキング) 
 https://momon-ga.com/popularity/
 
- コメント指数(話題性)
 https://momon-ga.com/comments/

- 高評価(いいね！)
 https://momon-ga.com/rated/

- マイリスト
 https://momon-ga.com/mylist/

- 閲覧履歴
 https://momon-ga.com/history/


### 作品のメタデータについて
このサイトでは作品ページにそれぞれメタデータが付いています。
メタデータのURLの形式をここに記しておきます。

- パロディのURLの例
 https://momon-ga.com/parody/%e8%89%a6%e9%9a%8a%e3%81%93%e3%82%8c%e3%81%8f%e3%81%97%e3%82%87%e3%82%93-%e8%89%a6%e3%81%93%e3%82%8c/
 
 - https://momon-ga.com/parody/%e3%82%bc%e3%83%ab%e3%83%80%e3%81%ae%e4%bc%9d%e8%aa%ac/


- サークルのURLの例
 https://momon-ga.com/group/%e5%b1%b1%e7%95%91%e7%92%83%e6%9d%8f/

- 作者のURLの例
 https://momon-ga.com/cartoonist/koikawa-minoru/
 https://momon-ga.com/cartoonist/%e8%8d%92%e4%ba%95%e5%95%93/
(作者名が半角英数字ならそのままらしい。　日本語とかだとこのようによくわからん文字列にされるけどこれも作者URL)

- キャラクターのURLの例
  https://momon-ga.com/character/producer/
  https://momon-ga.com/character/ami-mizuno/

- 内容 （タグ）ごとのURLの例
 https://momon-ga.com/tag/c96/
 https://momon-ga.com/tag/twintails/

- 検索結果のURLの例
 https://momon-ga.com/?s=%E9%A1%94%E5%8D%B0%E8%B1%A1%E9%9B%B6
 https://momon-ga.com/?s=pegging

